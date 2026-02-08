"""
Discord Adapter for MegaBot
Provides integration with Discord using discord.py

Features:
- Text messages and embeds
- File attachments
- Rich embeds with images, fields, etc.
- Guild and channel management
- Bot commands and interactions
- Message reactions
- Direct messages and server channels
- Voice channel info
"""

import asyncio
import logging
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, Mock

logger = logging.getLogger(__name__)

from core.resource_guard import LRUCache

try:
    import discord
    from discord import Embed, File
except ImportError:
    # Fallback mocks
    from unittest.mock import MagicMock

    discord = MagicMock()

    class Embed:
        def __init__(self, *args, **kwargs):
            pass

        def to_dict(self):
            return {}

    class File:
        def __init__(self, *args, **kwargs):
            pass


from adapters.messaging import MessageType, PlatformAdapter, PlatformMessage


@dataclass
class DiscordMessage:
    """Discord message object"""

    id: int
    channel_id: int
    guild_id: int | None
    author: str
    author_id: int
    content: str
    timestamp: datetime
    embeds: list[dict[str, Any]] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)
    reactions: list[dict[str, Any]] = field(default_factory=list)
    is_dm: bool = False

    @classmethod
    def from_message(cls, message: discord.Message) -> "DiscordMessage":
        return cls(
            id=message.id,
            channel_id=message.channel.id,
            guild_id=message.guild.id if message.guild else None,
            author=message.author.display_name,
            author_id=message.author.id,
            content=message.content,
            timestamp=message.created_at,
            embeds=[embed.to_dict() for embed in message.embeds],
            attachments=[
                {
                    "filename": a.filename,
                    "url": a.url,
                    "content_type": a.content_type,
                    "size": a.size,
                }
                for a in message.attachments
            ],
            mentions=[str(m) for m in message.mentions],
            reactions=[{"emoji": str(r.emoji), "count": r.count, "me": r.me} for r in message.reactions],
            is_dm=False,  # For mocking purposes, assume not DM
        )


class DiscordAdapter(PlatformAdapter):
    """
    Discord Bot API Adapter

    Provides comprehensive Discord integration:
    - Text messaging and embeds
    - File attachments and media
    - Guild and channel management
    - Slash commands and interactions
    - Message reactions and replies
    - Direct messages and server channels
    """

    def __init__(
        self,
        platform_name: str,
        server: Any,
        token: str,
        intents: discord.Intents | None = None,
        command_prefix: str = "!",
        admin_user_ids: list[int] | None = None,
    ):
        """
        Initialize the Discord adapter.

        Args:
            platform_name: Name of the platform ("discord")
            server: Reference to the MegaBotMessagingServer instance
            token: Discord bot token
            intents: Discord intents for the bot
            command_prefix: Prefix for bot commands
            admin_user_ids: User IDs with admin privileges
        """
        super().__init__(platform_name, server)
        self.token = token
        self.command_prefix = command_prefix
        self.admin_user_ids = admin_user_ids or []

        # Default intents
        if intents is None:
            intents = discord.Intents.default()
            intents.message_content = True
            intents.members = True
            intents.reactions = True

        self.bot = discord.Client(intents=intents)
        self.tree = discord.app_commands.CommandTree(self.bot)

        self.is_initialized = False
        self.message_cache: LRUCache[str, dict[str, Any]] = LRUCache(maxsize=1024)

        self.message_handlers: list[Callable] = []
        self.reaction_handlers: list[Callable] = []
        self.command_handlers: dict[str, Callable] = {}
        self.error_handlers: list[Callable] = []

        self._setup_event_handlers()

    def _setup_event_handlers(self) -> None:
        """Set up Discord event handlers"""

        @self.bot.event
        async def on_ready():
            logger.info("[Discord] Bot logged in as %s", self.bot.user)
            await self.tree.sync()

        @self.bot.event
        async def on_message(message: discord.Message):
            # Ignore messages from self
            if message.author == self.bot.user:
                return

            # Handle commands
            if message.content.startswith(self.command_prefix):
                await self._handle_command(message)
                return

            # Handle regular messages
            await self._handle_message(message)

        @self.bot.event
        async def on_reaction_add(reaction: discord.Reaction, user: discord.User):
            if user == self.bot.user:
                return

            for handler in self.reaction_handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(reaction, user, "add")
                    else:
                        handler(reaction, user, "add")
                except Exception as e:
                    logger.error("[Discord] Reaction handler error: %s", e)

        @self.bot.event
        async def on_reaction_remove(reaction: discord.Reaction, user: discord.User):
            if user == self.bot.user:
                return

            for handler in self.reaction_handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(reaction, user, "remove")
                    else:
                        handler(reaction, user, "remove")
                except Exception as e:
                    logger.error("[Discord] Reaction handler error: %s", e)

    async def _handle_command(self, message: discord.Message) -> None:
        """Handle bot commands"""
        parts = message.content[len(self.command_prefix) :].split()
        if not parts:
            return

        command = parts[0].lower()
        args = parts[1:]

        if command in self.command_handlers:
            try:
                if asyncio.iscoroutinefunction(self.command_handlers[command]):
                    await self.command_handlers[command](message, args)
                else:
                    self.command_handlers[command](message, args)
            except Exception as e:
                logger.error("[Discord] Command handler error: %s", e)
                await message.reply(f"Error executing command: {e}")

    async def _handle_message(self, message: discord.Message) -> None:
        """Handle regular messages"""
        platform_msg = await self._to_platform_message(message)

        for handler in self.message_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(platform_msg)
                else:
                    handler(platform_msg)
            except Exception as e:
                logger.error("[Discord] Message handler error: %s", e)

    async def _to_platform_message(self, message: discord.Message) -> PlatformMessage:
        """Convert Discord message to PlatformMessage"""
        content = message.content
        msg_type = MessageType.TEXT

        if message.attachments:
            if any(a.content_type and a.content_type.startswith("image/") for a in message.attachments):
                msg_type = MessageType.IMAGE
            elif any(a.content_type and a.content_type.startswith("video/") for a in message.attachments):
                msg_type = MessageType.VIDEO
            elif any(a.content_type and a.content_type.startswith("audio/") for a in message.attachments):
                msg_type = MessageType.AUDIO
            else:
                msg_type = MessageType.DOCUMENT

        # Add embed info to content
        if message.embeds:
            embed_info = []
            for embed in message.embeds:
                if embed.title:
                    embed_info.append(f"**{embed.title}**")
                if embed.description:
                    embed_info.append(embed.description)
                if embed.fields:
                    for field in embed.fields:
                        embed_info.append(f"**{field.name}:** {field.value}")
            if embed_info:
                content += "\n\n" + "\n".join(embed_info)

        return PlatformMessage(
            id=f"discord_{message.id}",
            platform="discord",
            sender_id=str(message.author.id),
            sender_name=message.author.display_name,
            chat_id=str(message.channel.id),
            content=content,
            message_type=msg_type,
            metadata={
                "discord_message_id": message.id,
                "discord_channel_id": message.channel.id,
                "discord_guild_id": message.guild.id if message.guild else None,
                "discord_author_id": message.author.id,
                "discord_timestamp": message.created_at.isoformat(),
                "discord_mentions": [str(m) for m in message.mentions],
                "discord_reactions": [{"emoji": str(r.emoji), "count": r.count, "me": r.me} for r in message.reactions],
                "discord_embeds": [embed.to_dict() for embed in message.embeds],
                "discord_attachments": [
                    {
                        "filename": a.filename,
                        "url": a.url,
                        "content_type": a.content_type,
                        "size": a.size,
                    }
                    for a in message.attachments
                ],
                "is_dm": hasattr(message.channel, "type") and str(getattr(message.channel, "type", "")).lower() == "dm",
            },
        )

    async def initialize(self) -> bool:
        """
        Initialize the Discord bot.

        Returns:
            True if initialization successful
        """
        try:
            await self.bot.start(self.token)
            self.is_initialized = True
            return True
        except Exception as e:
            logger.error("[Discord] Initialization failed: %s", e)
            return False

    async def shutdown(self) -> None:
        """Clean up resources"""
        if self.bot:
            await self.bot.close()
        self.is_initialized = False
        logger.info("[Discord] Adapter shutdown complete")

    async def send_message(
        self,
        channel_id: str,
        content: str,
        embed: Embed | None = None,
        embeds: list[Embed] | None = None,
        file: File | None = None,
        files: list[File] | None = None,
        reply_to: int | None = None,
        mention: bool = False,
    ) -> discord.Message | None:
        """
        Send a message to a Discord channel.

        Args:
            channel_id: Channel ID to send to
            content: Message content
            embed: Single embed to send
            embeds: List of embeds
            file: Single file to attach
            files: List of files to attach
            reply_to: Message ID to reply to
            mention: Whether to mention users

        Returns:
            Sent message or None on failure
        """
        try:
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                logger.warning("[Discord] Channel %s not found", channel_id)
                return None

            kwargs: dict[str, Any] = {"content": content}

            if embed:
                kwargs["embed"] = embed
            if embeds:
                kwargs["embeds"] = embeds
            if file:
                kwargs["file"] = file
            if files:
                kwargs["files"] = files

            if reply_to:
                # Find the message to reply to
                try:
                    reply_msg = await channel.fetch_message(reply_to)
                    kwargs["reference"] = reply_msg
                except discord.NotFound:
                    logger.warning("[Discord] Reply message %s not found", reply_to)

            return await channel.send(**kwargs)

        except Exception as e:
            logger.error("[Discord] Send message error: %s", e)
            return None

    async def send_embed(
        self,
        channel_id: str,
        title: str,
        description: str = "",
        color: discord.Color | None = None,
        fields: list[dict[str, str]] | None = None,
        thumbnail_url: str | None = None,
        image_url: str | None = None,
        footer_text: str | None = None,
        author_name: str | None = None,
        author_icon_url: str | None = None,
    ) -> discord.Message | None:
        """
        Send an embed message.

        Args:
            channel_id: Channel ID
            title: Embed title
            description: Embed description
            color: Embed color
            fields: List of field dicts with 'name' and 'value'
            thumbnail_url: Thumbnail image URL
            image_url: Main image URL
            footer_text: Footer text
            author_name: Author name
            author_icon_url: Author icon URL

        Returns:
            Sent message or None
        """
        if color is None:
            color = discord.Color.blue()
        embed = Embed(title=title, description=description, color=color)

        if fields:
            for field in fields:
                embed.add_field(
                    name=field["name"],
                    value=field["value"],
                    inline=field.get("inline", False),
                )

        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)
        if image_url:
            embed.set_image(url=image_url)
        if footer_text:
            embed.set_footer(text=footer_text)
        if author_name:
            embed.set_author(name=author_name, icon_url=author_icon_url)

        return await self.send_message(channel_id, "", embed=embed)

    async def create_channel(
        self,
        guild_id: str,
        name: str,
        channel_type: str = "text",
        topic: str | None = None,
        nsfw: bool = False,
        category_id: str | None = None,
    ) -> discord.TextChannel | None:
        """
        Create a new channel in a guild.

        Args:
            guild_id: Guild ID
            name: Channel name
            channel_type: 'text' or 'voice'
            topic: Channel topic (for text channels)
            nsfw: NSFW flag
            category_id: Category ID to place channel in

        Returns:
            Created channel or None
        """
        try:
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                return None

            kwargs = {"name": name, "nsfw": nsfw}

            if channel_type == "text":
                kwargs["topic"] = topic

            if category_id:
                category = guild.get_channel(int(category_id))
                if isinstance(category, discord.CategoryChannel):
                    kwargs["category"] = category

            return (
                await guild.create_text_channel(**kwargs)
                if channel_type == "text"
                else await guild.create_voice_channel(**kwargs)
            )

        except Exception as e:
            logger.error("[Discord] Create channel error: %s", e)
            return None

    async def get_channel_info(self, channel_id: str) -> dict[str, Any] | None:
        """Get information about a channel"""
        try:
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                return None

            info = {
                "id": str(channel.id),
                "name": channel.name,
                "type": str(channel.type),
                "position": getattr(channel, "position", None),
                "nsfw": getattr(channel, "nsfw", False),
                "topic": getattr(channel, "topic", None),
                "created_at": channel.created_at.isoformat() if channel.created_at else None,
            }

            if hasattr(channel, "guild") and channel.guild:
                info["guild_id"] = str(channel.guild.id)
                info["guild_name"] = channel.guild.name

            return info

        except Exception as e:
            logger.error("[Discord] Get channel info error: %s", e)
            return None

    async def get_guild_info(self, guild_id: str) -> dict[str, Any] | None:
        """Get information about a guild"""
        try:
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                return None

            return {
                "id": str(guild.id),
                "name": guild.name,
                "member_count": guild.member_count,
                "owner_id": str(guild.owner_id),
                "created_at": guild.created_at.isoformat(),
                "description": guild.description,
                "icon_url": guild.icon.url if guild.icon else None,
            }

        except Exception as e:
            logger.error("[Discord] Get guild info error: %s", e)
            return None

    async def add_reaction(self, channel_id: str, message_id: int, emoji: str) -> bool:
        """
        Add a reaction to a message.

        Args:
            channel_id: Channel ID
            message_id: Message ID
            emoji: Emoji to react with

        Returns:
            True on success
        """
        try:
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                return False

            message = await channel.fetch_message(message_id)
            await message.add_reaction(emoji)
            return True

        except Exception as e:
            logger.error("[Discord] Add reaction error: %s", e)
            return False

    async def remove_reaction(
        self,
        channel_id: str,
        message_id: int,
        emoji: str,
        user_id: str | None = None,
    ) -> bool:
        """
        Remove a reaction from a message.

        Args:
            channel_id: Channel ID
            message_id: Message ID
            emoji: Emoji to remove
            user_id: User ID (None for bot's reaction)

        Returns:
            True on success
        """
        try:
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                return False

            message = await channel.fetch_message(message_id)
            if user_id:
                user = await self.bot.fetch_user(int(user_id))
                await message.remove_reaction(emoji, user)
            else:
                await message.remove_reaction(emoji, self.bot.user)
            return True

        except Exception as e:
            logger.error("[Discord] Remove reaction error: %s", e)
            return False

    async def delete_message(self, channel_id: str, message_id: int) -> bool:
        """
        Delete a message.

        Args:
            channel_id: Channel ID
            message_id: Message ID

        Returns:
            True on success
        """
        try:
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                return False

            message = await channel.fetch_message(message_id)
            await message.delete()
            return True

        except Exception as e:
            logger.error("[Discord] Delete message error: %s", e)
            return False

    async def edit_message(
        self,
        channel_id: str,
        message_id: int,
        content: str,
        embed: Embed | None = None,
    ) -> bool:
        """
        Edit a message.

        Args:
            channel_id: Channel ID
            message_id: Message ID
            content: New content
            embed: New embed

        Returns:
            True on success
        """
        try:
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                return False

            message = await channel.fetch_message(message_id)
            kwargs = {"content": content}
            if embed:
                kwargs["embed"] = embed

            await message.edit(**kwargs)
            return True

        except Exception as e:
            logger.error("[Discord] Edit message error: %s", e)
            return False

    async def get_user_info(self, user_id: str) -> dict[str, Any] | None:
        """Get information about a user"""
        try:
            user = await self.bot.fetch_user(int(user_id))
            return {
                "id": str(user.id),
                "name": user.name,
                "display_name": user.display_name,
                "discriminator": user.discriminator,
                "avatar_url": user.avatar.url if user.avatar else None,
                "bot": user.bot,
                "created_at": user.created_at.isoformat(),
            }

        except Exception as e:
            logger.error("[Discord] Get user info error: %s", e)
            return None

    def register_message_handler(self, handler: Callable) -> None:
        """Register a message handler"""
        self.message_handlers.append(handler)

    def register_reaction_handler(self, handler: Callable) -> None:
        """Register a reaction handler"""
        self.reaction_handlers.append(handler)

    def register_command_handler(self, command: str, handler: Callable) -> None:
        """Register a command handler"""
        self.command_handlers[command] = handler

    def register_error_handler(self, handler: Callable) -> None:
        """Register an error handler"""
        self.error_handlers.append(handler)

    async def send_text(self, chat_id: str, text: str, reply_to: str | None = None) -> PlatformMessage | None:
        """Send text message to Discord channel."""
        try:
            message = await self.send_message(chat_id, text)
            if message:
                return await self._to_platform_message(message)
            return None
        except Exception as e:
            logger.error("[Discord] Send text error: %s", e)
            return None

    async def send_media(
        self,
        chat_id: str,
        media_path: str,
        caption: str | None = None,
        media_type: MessageType = MessageType.IMAGE,
    ) -> PlatformMessage | None:
        """Send media to Discord channel."""
        try:
            # For now, send as file attachment
            file = discord.File(media_path, filename=os.path.basename(media_path))
            message = await self.send_message(chat_id, caption or "", file=file)
            if message:
                return await self._to_platform_message(message)
            return None
        except Exception as e:
            logger.error("[Discord] Send media error: %s", e)
            return None

    async def send_document(
        self, chat_id: str, document_path: str, caption: str | None = None
    ) -> PlatformMessage | None:
        """Send document to Discord channel."""
        return await self.send_media(chat_id, document_path, caption, MessageType.DOCUMENT)

    async def download_media(self, message_id: str, save_path: str) -> str | None:
        """Download media from Discord message.

        Searches cached channels for the message, then downloads the first
        attachment to *save_path*.  Returns the saved file path on success,
        or None if the message/attachment cannot be found.
        """
        try:
            # Try every guild channel the bot can see
            for guild in self.bot.guilds:
                for channel in guild.text_channels:
                    try:
                        message = await channel.fetch_message(int(message_id))
                    except Exception:
                        continue
                    if not message.attachments:
                        return None
                    attachment = message.attachments[0]
                    await attachment.save(save_path)
                    return save_path
            logger.warning("[Discord] Message %s not found in any channel", message_id)
            return None
        except Exception as e:
            logger.error("[Discord] Download media error: %s", e)
            return None

    async def make_call(self, chat_id: str, is_video: bool = False) -> bool:
        """Initiate a call (not supported by Discord API)."""
        logger.warning("[Discord] Call initiation not supported for %s", chat_id)
        return False

    def add_slash_command(self, command: discord.app_commands.Command) -> None:
        """Add a slash command"""
        self.tree.add_command(command)

    async def handle_webhook(self, webhook_data: dict[str, Any]) -> PlatformMessage | None:
        """
        Handle incoming webhook data (for when Discord sends webhooks).

        Args:
            webhook_data: Raw webhook payload

        Returns:
            Processed PlatformMessage or None
        """
        # This would be used if setting up webhooks with Discord
        # For now, we rely on the bot events
        return None

    def _generate_id(self) -> str:
        """Generate unique message ID"""
        return str(uuid.uuid4())


# Example slash command
@discord.app_commands.command(name="ping", description="Responds with pong!")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")


async def main():
    """Example usage of Discord adapter"""
    # Mock token - replace with real token
    adapter = DiscordAdapter("discord", Mock(), token=os.environ["DISCORD_BOT_TOKEN"])

    # Add example slash command
    adapter.add_slash_command(ping)

    # Register handlers
    adapter.register_message_handler(lambda msg: print(f"Discord: {msg.content}"))

    if await adapter.initialize():
        print("Discord adapter ready!")

        # Keep running
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            await adapter.shutdown()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
