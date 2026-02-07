# MegaBot Voice & Calling Guide

MegaBot can interact via voice and real phone systems using specialized adapters and MCP servers.

## 🎙️ Voice Interaction Modes

### 1. Voice Notes (WhatsApp/Telegram)
MegaBot supports asynchronous voice messaging.
- **Inbound**: Send a voice note to your bot. It will be transcribed and stored in `memU`.
- **Outbound**: MegaBot can respond with an audio file (Ogg/MP3) using its internal Text-to-Speech (TTS).

### 2. Real Phone Calls (Twilio)
MegaBot can place outbound phone calls to real mobile or landline numbers.
- **Use Case**: Emergency alerts, appointment booking, or simple "Pick up the milk" reminders to a family member.
- **Setup**:
  1. Get a Twilio account and a phone number.
  2. Add credentials to `mega-config.yaml` under the `twilio-voice` MCP section.
  3. Commands: `!call +123456789 "Message to speak"`

### 3. AI Voice Agent (Vapi/Retell)
For low-latency, human-like conversations.
- Requires an account with **Vapi.ai** or **RetellAI**.
- MegaBot acts as the "Brain" (Tool Orchestrator) while the voice provider handles the audio stream.

## 🛠️ Developer Configuration

### Voice Interface
All voice services must implement the `VoiceInterface` found in `core/interfaces.py`:
```python
class VoiceInterface(Protocol):
    async def make_call(self, recipient_phone: str, script: str) -> str:
        ...
```

### Safety & Approvals
**ALL phone calls require manual approval by default.**
When MegaBot wants to make a call, it will send a request to your `approval_queue`. You must reply with `!yes` to allow the bot to dial the number.

---
*Note: WhatsApp and Telegram official bot APIs do NOT support initiating voice calls. Use Twilio for actual telephony.*
