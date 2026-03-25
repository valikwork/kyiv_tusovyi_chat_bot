import requests
import time
import os
from typing import Set, Dict

# Configuration - using environment variables for security
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID', "-1002329866894")
ADMIN_USER_ID = os.getenv('ADMIN_USER_ID', "274157532")

# Optional: Add rate limiting and moderation
RATE_LIMIT_MINUTES = int(os.getenv('RATE_LIMIT_MINUTES', '5'))
MAX_MESSAGE_LENGTH = int(os.getenv('MAX_MESSAGE_LENGTH', '4000'))

# Port for Railway (if using webhooks in the future)
PORT = int(os.environ.get('PORT', 5000))


class KyivTusovyiBot:
    def __init__(self, token: str, target_chat_id: str, admin_user_id: str):
        if not token:
            raise ValueError("BOT_TOKEN environment variable is required!")

        self.token = token
        self.target_chat_id = target_chat_id
        self.admin_user_id = admin_user_id
        self.last_update_id = 0
        self.running = True
        self.waiting_for_post: Dict[str, bool] = {}
        self.user_last_post: Dict[str, float] = {}
        self.blocked_users: Set[str] = set()

    def send_message(self, chat_id: str, text: str, parse_mode: str = 'Markdown') -> bool:
        """Send a message to any chat"""
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': parse_mode
        }

        try:
            response = requests.post(url, data=data, timeout=10)
            result = response.json()

            if result.get('ok'):
                print(f"✅ Message sent to chat {chat_id}")
                return True
            else:
                error_msg = result.get('description', 'Unknown error')
                print(f"❌ Error sending message: {error_msg}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"❌ Network error: {e}")
            return False
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return False

    def post_to_target_chat(self, text: str, user_name: str, user_id: str) -> bool:
        """Post a message to the target chat without user attribution"""
        return self.send_message(self.target_chat_id, text)

    def get_updates(self) -> dict:
        """Get updates from Telegram"""
        url = f"https://api.telegram.org/bot{self.token}/getUpdates"
        params = {'offset': self.last_update_id + 1, 'timeout': 10}

        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ Error getting updates: {e}")
            return {'ok': False, 'error': str(e)}
        except Exception as e:
            print(f"❌ Unexpected error getting updates: {e}")
            return {'ok': False, 'error': str(e)}

    def is_rate_limited(self, user_id: str) -> bool:
        """Check if user is rate limited"""
        if user_id not in self.user_last_post:
            return False

        time_since_last_post = time.time() - self.user_last_post[user_id]
        return time_since_last_post < (RATE_LIMIT_MINUTES * 60)

    def is_user_blocked(self, user_id: str) -> bool:
        """Check if user is blocked"""
        return user_id in self.blocked_users

    def handle_message(self, message: dict) -> None:
        """Handle all messages from users"""
        try:
            # Only respond to private (direct) messages
            if message['chat'].get('type') != 'private':
                return

            chat_id = str(message['chat']['id'])
            user_id = str(message['from']['id'])
            text = message.get('text', '').strip()
            user_name = message['from'].get('first_name', 'User')
            username = message['from'].get('username', '')

            # Use username if available, otherwise use first name
            display_name = f"@{username}" if username else user_name

            print(f"📩 Message from {display_name} (ID: {user_id}): {text}")

            # Check if user is blocked
            if self.is_user_blocked(user_id):
                self.send_message(chat_id, "❌ You have been blocked from using this bot.")
                return

            # Handle commands FIRST, even if user is waiting to post
            if text.startswith('/'):
                self.handle_command(message)
                return

            # Check if user is waiting to post their next message
            if user_id in self.waiting_for_post:
                # This is the message they want to post
                if text:
                    # Check message length
                    if len(text) > MAX_MESSAGE_LENGTH:
                        self.send_message(chat_id,
                                          f"❌ Message too long! Maximum {MAX_MESSAGE_LENGTH} characters allowed.")
                        return

                    # Check rate limiting (skip for admin)
                    if user_id != self.admin_user_id and self.is_rate_limited(user_id):
                        remaining_time = RATE_LIMIT_MINUTES * 60 - (time.time() - self.user_last_post[user_id])
                        minutes_left = int(remaining_time // 60)
                        seconds_left = int(remaining_time % 60)
                        self.send_message(chat_id,
                                          f"⏰ Please wait {minutes_left}m {seconds_left}s before posting again.")
                        return

                    print(f"📝 Posting message from {display_name}: {text}")

                    if self.post_to_target_chat(text, display_name, user_id):
                        self.send_message(chat_id, "✅ Message posted successfully!")
                        # Update last post time
                        self.user_last_post[user_id] = time.time()

                        # Log to console
                        print(f"✅ Message posted by {display_name} (ID: {user_id})")
                    else:
                        self.send_message(chat_id, "❌ Failed to post message. Please try again later.")
                else:
                    self.send_message(chat_id, "❌ Empty message received. Please send your message again.")

                # Remove user from waiting list
                del self.waiting_for_post[user_id]
                return

        except Exception as e:
            print(f"❌ Error handling message: {e}")

    def handle_command(self, message: dict) -> None:
        """Handle bot commands"""
        try:
            chat_id = str(message['chat']['id'])
            user_id = str(message['from']['id'])
            text = message.get('text', '').strip()
            user_name = message['from'].get('first_name', 'User')
            username = message['from'].get('username', '')
            display_name = f"@{username}" if username else user_name

            print(f"📩 Command from {display_name} (ID: {user_id}): {text}")

            # Admin-only commands
            if user_id == self.admin_user_id:
                if text.startswith('/block '):
                    try:
                        target_user_id = text.split(' ')[1].strip()
                        self.blocked_users.add(target_user_id)
                        self.send_message(chat_id, f"🚫 User {target_user_id} has been blocked.")
                        return
                    except IndexError:
                        self.send_message(chat_id, "❌ Usage: /block <user_id>")
                        return

                elif text.startswith('/unblock '):
                    try:
                        target_user_id = text.split(' ')[1].strip()
                        self.blocked_users.discard(target_user_id)
                        self.send_message(chat_id, f"✅ User {target_user_id} has been unblocked.")
                        return
                    except IndexError:
                        self.send_message(chat_id, "❌ Usage: /unblock <user_id>")
                        return

                elif text == '/blocked':
                    if self.blocked_users:
                        blocked_list = '\n'.join(self.blocked_users)
                        self.send_message(chat_id, f"🚫 Blocked users:\n{blocked_list}")
                    else:
                        self.send_message(chat_id, "ℹ️ No blocked users.")
                    return

            # Regular commands available to all users
            if text == '/start' or text == '/help':
                help_text = f"""
🤖 *Kyiv Tusovyi Bot*

*Available Commands:*
• `/post` - Post a message to the group
• `/status` - Check your status
• `/help` - Show this help
• `/cancel` - Cancel waiting for post

*How to post:*
1. Send `/post`
2. Send your message (it will be posted anonymously)
3. Bot will post it to the group

*Rules:*
• Maximum {MAX_MESSAGE_LENGTH} characters per message
• Rate limit: One post every {RATE_LIMIT_MINUTES} minutes
• Messages will be posted without attribution

*Formatting:*
• `*text*` = *bold*
• `_text_` = _italic_
• \`text\` = `code`
                """

                # Add admin commands to help if user is admin
                if user_id == self.admin_user_id:
                    help_text += """
*Admin Commands:*
• `/block <user_id>` - Block a user
• `/unblock <user_id>` - Unblock a user
• `/blocked` - List blocked users
                    """

                self.send_message(chat_id, help_text)

            elif text == '/post':
                # Check if user is blocked
                if self.is_user_blocked(user_id):
                    self.send_message(chat_id, "❌ You have been blocked from using this bot.")
                    return

                # Check rate limiting (skip for admin)
                if user_id != self.admin_user_id and self.is_rate_limited(user_id):
                    remaining_time = RATE_LIMIT_MINUTES * 60 - (time.time() - self.user_last_post[user_id])
                    minutes_left = int(remaining_time // 60)
                    seconds_left = int(remaining_time % 60)
                    self.send_message(chat_id, f"⏰ You can post again in {minutes_left}m {seconds_left}s.")
                    return

                # Put user in waiting mode
                self.waiting_for_post[user_id] = True
                self.send_message(chat_id,
                                  f"📝 Ready to post! Send me your next message and I'll post it to the group anonymously.\n\nSend `/cancel` to cancel.\n\nMax length: {MAX_MESSAGE_LENGTH} characters.")

            elif text == '/cancel':
                if user_id in self.waiting_for_post:
                    del self.waiting_for_post[user_id]
                    self.send_message(chat_id, "❌ Post cancelled.")
                else:
                    self.send_message(chat_id, "ℹ️ Nothing to cancel.")

            elif text == '/status':
                waiting_status = "Yes" if user_id in self.waiting_for_post else "No"
                blocked_status = "Yes" if self.is_user_blocked(user_id) else "No"

                # Calculate time until next post
                next_post_info = "Now"
                if user_id != self.admin_user_id and self.is_rate_limited(user_id):
                    remaining_time = RATE_LIMIT_MINUTES * 60 - (time.time() - self.user_last_post[user_id])
                    minutes_left = int(remaining_time // 60)
                    seconds_left = int(remaining_time % 60)
                    next_post_info = f"{minutes_left}m {seconds_left}s"

                status_text = f"""
📊 *Your Status*

👤 Name: {display_name}
🆔 User ID: `{user_id}`
📝 Waiting to post: {waiting_status}
🚫 Blocked: {blocked_status}
⏰ Can post in: {next_post_info}

*Bot Info:*
🎯 Target Group: `{self.target_chat_id}`
⚡ Rate limit: {RATE_LIMIT_MINUTES} minutes
📏 Max message: {MAX_MESSAGE_LENGTH} chars
                """

                if user_id == self.admin_user_id:
                    status_text += f"\n🔑 *Admin Status*\n✅ You have admin privileges"

                self.send_message(chat_id, status_text)

            elif text.startswith('/'):
                self.send_message(chat_id, "❓ Unknown command. Send `/help` for available commands.")

        except Exception as e:
            print(f"❌ Error handling command: {e}")

    def test_bot_connection(self) -> bool:
        """Test if bot token is valid"""
        test_url = f"https://api.telegram.org/bot{self.token}/getMe"
        try:
            response = requests.get(test_url, timeout=10)
            response.raise_for_status()
            result = response.json()

            if result.get('ok'):
                bot_info = result.get('result', {})
                print(f"✅ Bot token is valid! Bot: @{bot_info.get('username', 'unknown')}")
                return True
            else:
                print(f"❌ Invalid bot token! Error: {result.get('description', 'Unknown error')}")
                return False

        except Exception as e:
            print(f"❌ Error testing bot token: {e}")
            return False

    def run(self) -> None:
        """Main bot loop"""
        print("🤖 Kyiv Tusovyi Bot started! (Production version)")
        print(f"🎯 Target chat ID: {self.target_chat_id}")
        print(f"👤 Admin user ID: {self.admin_user_id}")
        print(f"⏰ Rate limit: {RATE_LIMIT_MINUTES} minutes")
        print(f"📏 Max message length: {MAX_MESSAGE_LENGTH} characters")
        print("📱 Any user can now send /start to use the bot!")
        print("🛑 Press Ctrl+C to stop")
        print("=" * 60)

        # Test bot token first
        if not self.test_bot_connection():
            print("❌ Bot startup failed - invalid token!")
            return

        while self.running:
            try:
                updates = self.get_updates()

                if updates and updates.get('ok'):
                    for update in updates.get('result', []):
                        self.last_update_id = update['update_id']

                        if 'message' in update:
                            message = update['message']
                            self.handle_message(message)

                time.sleep(1)  # Wait 1 second before checking again

            except KeyboardInterrupt:
                print("\n👋 Bot stopped by user!")
                self.running = False
                break
            except Exception as e:
                print(f"❌ Error in main loop: {e}")
                time.sleep(5)  # Wait 5 seconds before retrying

        print("🤖 Bot shut down gracefully.")


def main():
    """Initialize and run the bot"""
    try:
        # Validate required environment variables
        if not BOT_TOKEN:
            print("❌ ERROR: BOT_TOKEN environment variable is required!")
            print("Please set your bot token in Railway environment variables.")
            return

        bot = KyivTusovyiBot(BOT_TOKEN, CHAT_ID, ADMIN_USER_ID)
        bot.run()

    except Exception as e:
        print(f"❌ Failed to start bot: {e}")


if __name__ == '__main__':
    main()
