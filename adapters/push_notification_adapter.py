"""
Smartphone Push Notification Adapter for MegaBot
Provides push notification support for:
- Android devices via Firebase Cloud Messaging (FCM)
- iOS devices via Apple Push Notification Service (APNS)

Features:
- Send push notifications to individual devices
- Send to device groups
- Rich notifications with images, actions, and custom data
- Notification channels (Android)
- Badge management (iOS)
- Delivery tracking
- Topics/messaging for broadcast notifications
"""

import asyncio
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable

try:
    import firebase_admin
    from firebase_admin import credentials, messaging
    from firebase_admin import App as firebase_app

    _HAS_FIREBASE = True
except ImportError:
    firebase_admin = None  # type: ignore[assignment]
    credentials = None  # type: ignore[assignment]
    messaging = None  # type: ignore[assignment]
    firebase_app = None  # type: ignore[assignment]
    _HAS_FIREBASE = False

from core.resource_guard import LRUCache


class Platform(Enum):
    """Device platforms"""

    ANDROID = "android"
    IOS = "ios"
    WEB = "web"


class Priority(Enum):
    """Message priority"""

    NORMAL = "normal"
    HIGH = "high"


class NotificationType(Enum):
    """Types of notifications"""

    MESSAGE = "message"
    ALERT = "alert"
    UPDATE = "update"
    REMINDER = "reminder"
    SYSTEM = "system"


@dataclass
class PushNotification:
    """Push notification payload"""

    title: str
    body: str
    notification_type: NotificationType = NotificationType.MESSAGE
    image_url: Optional[str] = None
    icon: Optional[str] = None
    sound: Optional[str] = None
    badge: Optional[int] = None
    tag: Optional[str] = None
    color: Optional[str] = None
    click_action: Optional[str] = None
    channel_id: Optional[str] = None
    ticker: Optional[str] = None
    sticky: bool = False
    local_only: bool = False
    priority: Priority = Priority.HIGH
    data: Dict[str, str] = field(default_factory=dict)
    actions: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"title": self.title, "body": self.body}

        if self.image_url:
            result["image"] = self.image_url
        if self.icon:
            result["icon"] = self.icon
        if self.sound:
            result["sound"] = self.sound
        if self.badge is not None:
            result["badge"] = self.badge
        if self.tag:
            result["tag"] = self.tag
        if self.color:
            result["color"] = self.color
        if self.click_action:
            result["click_action"] = self.click_action
        if self.channel_id:
            result["channel_id"] = self.channel_id
        if self.ticker:
            result["ticker"] = self.ticker
        if self.sticky:
            result["sticky"] = self.sticky
        if self.local_only:
            result["local_only"] = self.local_only

        return result


@dataclass
class AndroidConfig:
    """Android-specific notification configuration"""

    collapse_key: Optional[str] = None
    priority: Priority = Priority.HIGH
    notification: Optional[PushNotification] = None
    data: Dict[str, str] = field(default_factory=dict)
    direct_boot_ok: bool = False
    restricted_package_name: Optional[str] = None
    timeout: int = 30

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}

        if self.collapse_key:
            result["collapse_key"] = self.collapse_key
        result["priority"] = self.priority.value

        if self.notification:
            result["notification"] = self.notification.to_dict()
        if self.data:
            result["data"] = self.data
        if self.direct_boot_ok:
            result["direct_boot_ok"] = self.direct_boot_ok
        if self.restricted_package_name:
            result["restricted_package_name"] = self.restricted_package_name

        return result


@dataclass
class ApnsConfig:
    """APNS-specific notification configuration"""

    bundle_id: str
    badge: Optional[int] = None
    sound: Optional[str] = None
    category: Optional[str] = None
    thread_id: Optional[str] = None
    content_available: bool = False
    mutable_content: bool = False
    priority: int = 10
    apns_push_type: str = "alert"
    collapse_id: Optional[str] = None
    expiration: Optional[int] = None
    topic: Optional[str] = None
    custom_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "aps": {"content-available" if self.content_available else "alert": 1 if self.content_available else {}}
        }

        if self.badge is not None:
            result["aps"]["badge"] = self.badge
        if self.sound:
            result["aps"]["sound"] = self.sound
        if self.category:
            result["aps"]["category"] = self.category
        if self.thread_id:
            result["aps"]["thread-id"] = self.thread_id
        if self.mutable_content:
            result["aps"]["mutable-content"] = 1
        if self.collapse_id:
            result["aps"]["collapse-id"] = self.collapse_id
        if self.expiration:
            result["aps"]["expiration"] = self.expiration
        if self.topic:
            result["aps"]["topic"] = self.topic

        result["aps"]["push-type"] = self.apns_push_type

        for key, value in self.custom_data.items():
            if key not in result["aps"]:
                result[key] = value

        return result


@dataclass
class WebpushConfig:
    """Web push configuration"""

    notification: Optional[PushNotification] = None
    data: Dict[str, str] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)
    ttl: int = 2419200

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}

        if self.notification:
            result["notification"] = self.notification.to_dict()
        if self.data:
            result["data"] = self.data
        if self.headers:
            result["headers"] = self.headers
        result["ttl"] = self.ttl

        return result


@dataclass
class DeviceToken:
    """Device registration token"""

    token: str
    platform: Platform
    user_id: Optional[str] = None
    app_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    is_active: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeviceToken":
        return cls(
            token=data.get("token", ""),
            platform=Platform(data.get("platform", "android")),
            user_id=data.get("user_id"),
            app_id=data.get("app_id"),
            created_at=datetime.fromisoformat(data.get("created_at", datetime.now().isoformat())),
            last_active=datetime.fromisoformat(data.get("last_active", datetime.now().isoformat())),
            is_active=data.get("is_active", True),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token": self.token,
            "platform": self.platform.value,
            "user_id": self.user_id,
            "app_id": self.app_id,
            "created_at": self.created_at.isoformat(),
            "last_active": self.last_active.isoformat(),
            "is_active": self.is_active,
        }


@dataclass
class NotificationChannel:
    """Android notification channel"""

    id: str
    name: str
    description: Optional[str] = None
    importance: int = 4
    enable_vibration: bool = True
    enable_lights: bool = True
    show_badge: bool = True
    vibration_pattern: Optional[List[int]] = None
    sound: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel_id": self.id,
            "name": self.name,
            "description": self.description,
            "importance": self.importance,
            "enable_vibration": self.enable_vibration,
            "enable_lights": self.enable_lights,
            "show_badge": self.show_badge,
            "vibration_pattern": self.vibration_pattern,
            "sound": self.sound,
        }


@dataclass
class NotificationResult:
    """Result of sending a notification"""

    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None
    errors: List[Dict[str, Any]] = field(default_factory=list)
    canonical_token: Optional[bool] = None

    @classmethod
    def from_firebase(cls, response: messaging.SendResponse) -> "NotificationResult":
        if getattr(response, "exception", None):
            return cls(success=False, error=str(response.exception))
        canonical = False
        try:
            canonical = bool(getattr(response, "canonical_address_count", 0) > 0)
        except Exception:
            canonical = False
        return cls(
            success=True,
            message_id=getattr(response, "message_id", None),
            canonical_token=canonical,
        )


class PushNotificationAdapter:
    """
    Multi-platform Push Notification Adapter

    Supports:
    - Firebase Cloud Messaging (FCM) for Android/Web
    - Apple Push Notification Service (APNS) for iOS

    Features:
    - Single device notifications
    - Device groups
    - Topics/messaging
    - Rich notifications
    - Notification channels (Android)
    - Badge management (iOS)
    - Delivery tracking
    - Token management
    """

    def __init__(
        self,
        fcm_credential_path: Optional[str] = None,
        fcm_project_id: Optional[str] = None,
        apns_key_path: Optional[str] = None,
        apns_key_id: Optional[str] = None,
        apns_bundle_id: Optional[str] = None,
        apns_team_id: Optional[str] = None,
        apns_sandbox: bool = True,
        token_storage_path: str = "./data/push_tokens.json",
        default_channel_id: str = "megabot_default",
        admin_user_ids: Optional[List[str]] = None,
    ):
        """
        Initialize the push notification adapter.

        Args:
            fcm_credential_path: Path to FCM service account JSON
            fcm_project_id: FCM project ID
            apns_key_path: Path to APNS auth key (.p8)
            apns_key_id: APNS key ID
            apns_bundle_id: iOS app bundle ID
            apns_team_id: Apple team ID
            apns_sandbox: Use APNS sandbox or production
            token_storage_path: Path to store device tokens
            default_channel_id: Default Android notification channel
            admin_user_ids: User IDs with admin privileges
        """
        self.fcm_credential_path = fcm_credential_path
        self.fcm_project_id = fcm_project_id
        self.apns_key_path = apns_key_path
        self.apns_key_id = apns_key_id
        self.apns_bundle_id = apns_bundle_id
        self.apns_team_id = apns_team_id
        self.apns_sandbox = apns_sandbox
        self.token_storage_path = token_storage_path
        self.default_channel_id = default_channel_id
        self.admin_user_ids = admin_user_ids or []

        self._firebase_app: Optional[firebase_app] = None
        self._is_initialized = False

        self.device_tokens: LRUCache[str, DeviceToken] = LRUCache(maxsize=4096)
        self.notification_channels: Dict[str, NotificationChannel] = {}

        self.message_handlers: List[Callable] = []
        self.token_update_handlers: List[Callable] = []
        self.error_handlers: List[Callable] = []

    async def initialize(self) -> bool:
        """
        Initialize the adapter and services.

        Returns:
            True if initialization successful
        """
        if not _HAS_FIREBASE:
            print("[Push] firebase-admin not installed — push notifications unavailable")
            return False
        try:
            self._initialize_fcm()
            self._load_tokens()
            self._create_default_channels()

            self._is_initialized = True
            print("[Push] Adapter initialized")
            return True

        except Exception as e:
            print(f"[Push] Initialization failed: {e}")
            return False

    def shutdown(self) -> None:
        """Clean up resources"""
        self._save_tokens()
        if self._firebase_app:
            try:
                firebase_admin.delete_app(self._firebase_app)
            except ValueError:
                # Tolerate mocks or already-deleted apps
                pass
            self._firebase_app = None
        self._is_initialized = False
        print("[Push] Adapter shutdown complete")

    def _initialize_fcm(self) -> None:
        """Initialize Firebase Cloud Messaging"""
        if self.fcm_credential_path and os.path.exists(self.fcm_credential_path):
            try:
                cred = credentials.Certificate(self.fcm_credential_path)
            except Exception:
                cred = None

            try:
                self._firebase_app = firebase_admin.initialize_app(cred, {"projectId": self.fcm_project_id})
                print(f"[Push] FCM initialized with project: {self.fcm_project_id}")
            except Exception as e:
                print(f"[Push] FCM initialization warning: {e}")
        else:
            print("[Push] No FCM credentials provided, FCM disabled")

    def _load_tokens(self) -> None:
        """Load device tokens from storage"""
        try:
            if os.path.exists(self.token_storage_path):
                with open(self.token_storage_path, "r") as f:
                    tokens_data = json.load(f)
                    for token_data in tokens_data:
                        token = DeviceToken.from_dict(token_data)
                        self.device_tokens[token.token] = token
                print(f"[Push] Loaded {len(self.device_tokens)} device tokens")
        except Exception as e:
            print(f"[Push] Failed to load tokens: {e}")

    def _save_tokens(self) -> None:
        """Save device tokens to storage"""
        try:
            os.makedirs(os.path.dirname(self.token_storage_path), exist_ok=True)
            tokens_data = [token.to_dict() for token in self.device_tokens.values()]
            with open(self.token_storage_path, "w") as f:
                json.dump(tokens_data, f)
        except Exception as e:
            print(f"[Push] Failed to save tokens: {e}")

    def _create_default_channels(self) -> None:
        """Create default notification channels"""
        channels = [
            NotificationChannel(
                id="megabot_default",
                name="MegaBot Messages",
                description="General notifications from MegaBot",
                importance=4,
            ),
            NotificationChannel(
                id="megabot_alerts",
                name="Alerts",
                description="Important alerts and reminders",
                importance=5,
                enable_vibration=True,
            ),
            NotificationChannel(
                id="megabot_messages",
                name="Messages",
                description="Direct messages and conversations",
                importance=4,
            ),
            NotificationChannel(
                id="megabot_silent",
                name="Silent",
                description="Silent notifications without sound",
                importance=2,
                enable_vibration=False,
                sound=None,
            ),
        ]

        for channel in channels:
            self.notification_channels[channel.id] = channel

    async def register_token(
        self,
        token: str,
        platform: Platform,
        user_id: Optional[str] = None,
        app_id: Optional[str] = None,
    ) -> bool:
        """
        Register a device token.

        Args:
            token: Device registration token
            platform: Device platform (android/ios/web)
            user_id: Associated user ID
            app_id: Application ID

        Returns:
            True if registration successful
        """
        try:
            device_token = DeviceToken(token=token, platform=platform, user_id=user_id, app_id=app_id)

            self.device_tokens[token] = device_token
            self._save_tokens()

            for handler in self.token_update_handlers:
                try:
                    handler("registered", token)
                except Exception as e:
                    print(f"[Push] Token handler error: {e}")

            return True

        except Exception as e:
            print(f"[Push] Token registration failed: {e}")
            return False

    async def unregister_token(self, token: str) -> bool:
        """
        Unregister a device token.

        Args:
            token: Device registration token

        Returns:
            True if unregistration successful
        """
        try:
            if token in self.device_tokens:
                del self.device_tokens[token]
                self._save_tokens()

                for handler in self.token_update_handlers:
                    try:
                        handler("unregistered", token)
                    except Exception as e:
                        print(f"[Push] Token handler error: {e}")

            return True

        except Exception as e:
            print(f"[Push] Token unregistration failed: {e}")
            return False

    async def send_to_token(
        self,
        token: str,
        notification: PushNotification,
        platform: Optional[Platform] = None,
        android_config: Optional[AndroidConfig] = None,
        apns_config: Optional[ApnsConfig] = None,
        webpush_config: Optional[WebpushConfig] = None,
        dry_run: bool = False,
    ) -> NotificationResult:
        """
        Send notification to a specific device token.

        Args:
            token: Device registration token
            notification: Notification payload
            platform: Device platform (auto-detected if not provided)
            platform_config: Platform-specific configuration
            dry_run: Validate without sending

        Returns:
            NotificationResult with success status and details
        """
        try:
            if platform is None:
                device_token = self.device_tokens.get(token)
                platform = device_token.platform if device_token else Platform.ANDROID

            if platform == Platform.ANDROID:
                return await self._send_fcm(
                    token=token,
                    notification=notification,
                    config=android_config,
                    dry_run=dry_run,
                )
            elif platform == Platform.IOS:
                return await self._send_apns(
                    token=token,
                    notification=notification,
                    config=apns_config,
                    dry_run=dry_run,
                )
            elif platform == Platform.WEB:
                return await self._send_webpush(
                    token=token,
                    notification=notification,
                    config=webpush_config,
                    dry_run=dry_run,
                )
            else:
                return NotificationResult(success=False, error=f"Unknown platform: {platform}")

        except Exception as e:
            print(f"[Push] Send to token failed: {e}")
            return NotificationResult(success=False, error=str(e))

    async def send_to_user(
        self,
        user_id: str,
        notification: PushNotification,
        platform: Optional[Platform] = None,
        android_config: Optional[AndroidConfig] = None,
        apns_config: Optional[ApnsConfig] = None,
        webpush_config: Optional[WebpushConfig] = None,
        dry_run: bool = False,
    ) -> NotificationResult:
        """
        Send notification to all devices of a user.

        Args:
            user_id: User ID
            notification: Notification payload
            platform: Specific platform or None for all
            platform_config: Platform-specific configuration
            dry_run: Validate without sending

        Returns:
            Combined notification result
        """
        try:
            user_tokens = [
                token for token in self.device_tokens.values() if token.user_id == user_id and token.is_active
            ]

            if platform:
                user_tokens = [t for t in user_tokens if t.platform == platform]

            if not user_tokens:
                return NotificationResult(success=False, error=f"No active tokens found for user: {user_id}")

            results = []
            for token in user_tokens:
                result = await self.send_to_token(
                    token=token.token,
                    notification=notification,
                    platform=token.platform,
                    android_config=android_config,
                    apns_config=apns_config,
                    webpush_config=webpush_config,
                    dry_run=dry_run,
                )
                results.append(result)

            success_count = sum(1 for r in results if r.success)
            return NotificationResult(
                success=success_count > 0,
                error=None if success_count == len(results) else f"{success_count}/{len(results)} sent",
            )

        except Exception as e:
            print(f"[Push] Send to user failed: {e}")
            return NotificationResult(success=False, error=str(e))

    async def send_broadcast(
        self,
        notification: PushNotification,
        topic: Optional[str] = None,
        condition: Optional[str] = None,
        android_config: Optional[AndroidConfig] = None,
        apns_config: Optional[ApnsConfig] = None,
        dry_run: bool = False,
    ) -> NotificationResult:
        """
        Send notification to multiple devices via topic or condition.

        Args:
            notification: Notification payload
            topic: FCM topic (e.g., 'news', 'alerts')
            condition: FCM condition string (e.g., "'TopicA' in topics || 'TopicB' in topics")
            platform_config: Platform-specific configuration
            dry_run: Validate without sending

        Returns:
            NotificationResult with success status
        """
        try:
            if not self._firebase_app:
                return NotificationResult(success=False, error="FCM not initialized")

            if topic:
                msg = messaging.Message(
                    notification=messaging.Notification(
                        title=notification.title,
                        body=notification.body,
                        image=notification.image_url,
                    ),
                    topic=topic,
                    android=messaging.AndroidConfig(priority=self._to_fcm_priority(notification.priority)),
                )
            elif condition:
                msg = messaging.Message(
                    notification=messaging.Notification(
                        title=notification.title,
                        body=notification.body,
                        image=notification.image_url,
                    ),
                    condition=condition,
                    android=messaging.AndroidConfig(priority=self._to_fcm_priority(notification.priority)),
                )
            else:
                # Send to all registered tokens
                active_tokens = [token.token for token in self.device_tokens.values() if token.is_active]
                if not active_tokens:
                    return NotificationResult(success=False, error="No active tokens registered")

                msg = messaging.MulticastMessage(
                    notification=messaging.Notification(
                        title=notification.title,
                        body=notification.body,
                        image=notification.image_url,
                    ),
                    tokens=active_tokens,
                    android=messaging.AndroidConfig(
                        priority=self._to_fcm_priority(notification.priority),
                        notification=messaging.AndroidNotification(
                            channel_id=notification.channel_id or self.default_channel_id,
                            click_action=notification.click_action,
                            color=notification.color,
                            tag=notification.tag,
                            ticker=notification.ticker,
                            sticky=notification.sticky,
                            local_only=notification.local_only,
                        )
                        if notification
                        else None,
                    ),
                )

            response = messaging.send_each_for_multicast_sync(  # type: ignore[attr-defined]
                msg, dry_run=dry_run
            )
            return NotificationResult(
                success=response.success_count > 0,
                error=response.failure_count > 0 and "Some messages failed" or None,
            )

        except Exception as e:
            print(f"[Push] Broadcast failed: {e}")
            return NotificationResult(success=False, error=str(e))

    async def send_to_topic(
        self,
        topic: str,
        notification: PushNotification,
        android_config: Optional[AndroidConfig] = None,
        dry_run: bool = False,
    ) -> NotificationResult:
        """
        Send notification to an FCM topic.

        Args:
            topic: Topic name (without /topics/ prefix)
            notification: Notification payload
            platform_config: Platform-specific configuration
            dry_run: Validate without sending

        Returns:
            NotificationResult with success status
        """
        try:
            if not self._firebase_app:
                return NotificationResult(success=False, error="FCM not initialized")

            msg = messaging.Message(
                topic=topic,
                notification=messaging.Notification(
                    title=notification.title,
                    body=notification.body,
                    image=notification.image_url,
                ),
                android=messaging.AndroidConfig(
                    priority=self._to_fcm_priority(notification.priority),
                    notification=messaging.AndroidNotification(
                        channel_id=notification.channel_id or self.default_channel_id
                    ),
                ),
            )

            if dry_run:
                return NotificationResult(success=True)

            response = messaging.send(msg)
            return NotificationResult(success=True, message_id=response)

        except Exception as e:
            print(f"[Push] Send to topic failed: {e}")
            return NotificationResult(success=False, error=str(e))

    async def subscribe_to_topic(self, tokens: List[str], topic: str) -> bool:
        """
        Subscribe devices to an FCM topic.

        Args:
            tokens: List of device tokens
            topic: Topic name

        Returns:
            True if subscription successful
        """
        try:
            if not self._firebase_app:
                return False

            response = messaging.subscribe_to_topic(tokens, topic)
            return response.success_count == len(tokens)

        except Exception as e:
            print(f"[Push] Topic subscription failed: {e}")
            return False

    async def unsubscribe_from_topic(self, tokens: List[str], topic: str) -> bool:
        """
        Unsubscribe devices from an FCM topic.

        Args:
            tokens: List of device tokens
            topic: Topic name

        Returns:
            True if unsubscription successful
        """
        try:
            if not self._firebase_app:
                return False

            response = messaging.unsubscribe_from_topic(tokens, topic)
            return response.success_count == len(tokens)

        except Exception as e:
            print(f"[Push] Topic unsubscription failed: {e}")
            return False

    async def send_apns_void(
        self,
        token: str,
        bundle_id: str,
        topic: Optional[str] = None,
        collapse_id: Optional[str] = None,
    ) -> NotificationResult:
        """
        Send an APNS void (retract) notification.

        Args:
            token: Device token
            bundle_id: App bundle ID
            topic: APNS topic (usually bundle_id + '.push-type.voip')
            collapse_id: Collapse ID to void

        Returns:
            NotificationResult
        """
        try:
            import httpx

            apns_topic = topic or f"{bundle_id}.push-type.alert"

            url = "https://api.push.apple.com/void/{bundle_id}"
            headers = {
                "authorization": f"bearer {await self._get_apns_jwt()}",
                "apns-topic": apns_topic,
                "apns-collapse-id": collapse_id or "",
            }

            async with httpx.AsyncClient() as client:
                response = await client.delete(url.format(bundle_id=bundle_id), headers=headers)

            return NotificationResult(success=response.status_code == 204)

        except Exception as e:
            print(f"[Push] APNS void failed: {e}")
            return NotificationResult(success=False, error=str(e))

    async def _send_fcm(
        self,
        token: str,
        notification: PushNotification,
        config: Optional[AndroidConfig] = None,
        dry_run: bool = False,
    ) -> NotificationResult:
        """Send notification via FCM"""
        try:
            if not self._firebase_app:
                return NotificationResult(success=False, error="FCM not initialized")

            msg = messaging.Message(
                token=token,
                notification=messaging.Notification(
                    title=notification.title,
                    body=notification.body,
                    image=notification.image_url,
                ),
                android=messaging.AndroidConfig(
                    priority=self._to_fcm_priority(notification.priority),
                    notification=messaging.AndroidNotification(
                        channel_id=notification.channel_id or self.default_channel_id,
                        click_action=notification.click_action,
                        color=notification.color,
                        tag=notification.tag,
                        ticker=notification.ticker,
                        sticky=notification.sticky,
                        local_only=notification.local_only,
                        icon=notification.icon,
                        sound=notification.sound,
                    )
                    if notification
                    else None,
                ),
                data=notification.data,
            )

            if dry_run:
                return NotificationResult(success=True)

            response = messaging.send(msg)
            return NotificationResult(success=True, message_id=response)

        except Exception as e:
            error_str = str(e)
            if "UNREGISTERED" in error_str:
                await self.unregister_token(token)
                return NotificationResult(success=False, error="Token unregistered")
            return NotificationResult(success=False, error=error_str)

    async def _send_apns(
        self,
        token: str,
        notification: PushNotification,
        config: Optional[ApnsConfig] = None,
        dry_run: bool = False,
    ) -> NotificationResult:
        """Send notification via APNS"""
        try:
            bundle_id = config.bundle_id if config else self.apns_bundle_id
            if not bundle_id:
                return NotificationResult(success=False, error="APNS bundle ID not configured")

            apns_config = messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(
                        alert=messaging.ApsAlert(
                            title=notification.title,
                            body=notification.body,
                            launch_image=notification.image_url,
                        ),
                        sound=notification.sound or "default",
                        badge=notification.badge,
                        category=notification.tag,
                        thread_id=notification.click_action,
                        content_available=notification.data.get("content_available", False),
                        mutable_content=notification.data.get("mutable_content", False),
                    )
                )
            )

            msg = messaging.Message(token=token, apns=apns_config, data=notification.data)

            if dry_run:
                return NotificationResult(success=True)

            response = messaging.send(msg)
            return NotificationResult(success=True, message_id=response)

        except Exception as e:
            print(f"[Push] APNS send failed: {e}")
            return NotificationResult(success=False, error=str(e))

    async def _send_webpush(
        self,
        token: str,
        notification: PushNotification,
        config: Optional[WebpushConfig] = None,
        dry_run: bool = False,
    ) -> NotificationResult:
        """Send notification via Web Push"""
        try:
            webpush_config = messaging.WebpushConfig(
                notification=messaging.WebpushNotification(
                    title=notification.title,
                    body=notification.body,
                    icon=notification.icon,
                    image=notification.image_url,
                    badge=notification.badge,
                    vibrate=notification.data.get("vibrate"),
                    tag=notification.tag,
                    renotify=True,
                ),
                data=notification.data,
            )

            msg = messaging.Message(token=token, webpush=webpush_config)

            if dry_run:
                return NotificationResult(success=True)

            response = messaging.send(msg)
            return NotificationResult(success=True, message_id=response)

        except Exception as e:
            print(f"[Push] WebPush send failed: {e}")
            return NotificationResult(success=False, error=str(e))

    def _to_fcm_priority(self, priority: Priority) -> str:
        """Convert Priority to FCM priority string"""
        return "high" if priority == Priority.HIGH else "normal"

    async def _get_apns_jwt(self) -> str:
        """Generate APNS JWT token"""
        import time
        import jwt

        if not self.apns_key_path or not self.apns_key_id:
            return ""

        try:
            with open(self.apns_key_path, "r") as f:
                private_key = f.read()
        except Exception:
            return ""

        now = int(time.time())
        payload = {"iss": self.apns_team_id, "iat": now}

        try:
            token = jwt.encode(
                payload,
                private_key,
                algorithm="ES256",
                headers={"kid": self.apns_key_id},
            )
            return token
        except Exception:
            return ""

    async def create_notification_channel(self, channel: NotificationChannel) -> bool:
        """
        Create an Android notification channel.

        Args:
            channel: Notification channel configuration

        Returns:
            True if created successfully
        """
        try:
            self.notification_channels[channel.id] = channel
            return True
        except Exception as e:
            print(f"[Push] Channel creation failed: {e}")
            return False

    async def delete_notification_channel(self, channel_id: str) -> bool:
        """
        Delete an Android notification channel.

        Args:
            channel_id: Channel ID to delete

        Returns:
            True if deleted successfully
        """
        try:
            if channel_id in self.notification_channels:
                del self.notification_channels[channel_id]
            return True
        except Exception as e:
            print(f"[Push] Channel deletion failed: {e}")
            return False

    async def get_active_tokens(
        self, user_id: Optional[str] = None, platform: Optional[Platform] = None
    ) -> List[DeviceToken]:
        """
        Get active device tokens.

        Args:
            user_id: Filter by user ID
            platform: Filter by platform

        Returns:
            List of active device tokens
        """
        tokens = [t for t in self.device_tokens.values() if t.is_active]

        if user_id:
            tokens = [t for t in tokens if t.user_id == user_id]
        if platform:
            tokens = [t for t in tokens if t.platform == platform]

        return tokens

    async def cleanup_inactive_tokens(self, max_inactive_days: int = 30) -> int:
        """
        Remove tokens that haven't been active.

        Args:
            max_inactive_days: Days of inactivity before removal

        Returns:
            Number of tokens removed
        """
        try:
            from datetime import timedelta

            cutoff = datetime.now() - timedelta(days=max_inactive_days)

            removed = 0
            for token in list(self.device_tokens.values()):
                if token.last_active < cutoff:
                    await self.unregister_token(token.token)
                    removed += 1

            return removed

        except Exception as e:
            print(f"[Push] Token cleanup failed: {e}")
            return 0

    def register_message_handler(self, handler: Callable) -> None:
        """Register a message handler"""
        self.message_handlers.append(handler)

    def register_token_handler(self, handler: Callable) -> None:
        """Register a token update handler"""
        self.token_update_handlers.append(handler)

    def register_error_handler(self, handler: Callable) -> None:
        """Register an error handler"""
        self.error_handlers.append(handler)

    def _generate_id(self) -> str:
        """Generate unique notification ID"""
        return str(uuid.uuid4())


def create_notification(
    title: str,
    body: str,
    notification_type: NotificationType = NotificationType.MESSAGE,
    **kwargs,
) -> PushNotification:
    """
    Factory function to create a push notification.

    Args:
        title: Notification title
        body: Notification body
        notification_type: Type of notification
        **kwargs: Additional notification properties

    Returns:
        PushNotification instance
    """
    return PushNotification(title=title, body=body, notification_type=notification_type, **kwargs)


async def main():
    """Example usage of Push Notification adapter"""
    adapter = PushNotificationAdapter(
        fcm_credential_path="/path/to/firebase-credentials.json",
        fcm_project_id="my-project",
        apns_key_path="/path/to/AuthKey.p8",
        apns_key_id="KEY123",
        apns_bundle_id="com.example.app",
        apns_team_id="TEAM123",
    )

    if await adapter.initialize():
        print("Push adapter ready!")

        await adapter.register_token(token=os.environ["FCM_TOKEN"], platform=Platform.ANDROID, user_id="user123")

        notification = create_notification(
            title="Hello!",
            body="This is a push notification",
            notification_type=NotificationType.MESSAGE,
        )

        result = await adapter.send_to_token(token=os.environ["FCM_TOKEN"], notification=notification)

        print(f"Send result: {result.success}")


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
