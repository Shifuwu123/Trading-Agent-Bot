import os
import sys

# Ensure the project root is in the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from tradingbot.core.bot import TradingBot
from tradingbot.interfaces.telegram.telegram_listener import TelegramListener
from tradingbot.utils.logger import log

import argparse

def main():
    parser = argparse.ArgumentParser(description="Tredding Bot - Automated Crypto Trading Agent")
    parser.add_argument("--test", action="store_true", help="Run in test mode (no trading)")
    args = parser.parse_args()

    log.info("Initializing TradingBot Application...")
    try:
        bot = TradingBot()
        # Starts the bot scheduler in background thread
        bot.start() 
        
        # Starts the telegram listener (blocks the main thread to listen to updates)
        listener = TelegramListener(bot)
        listener.start_polling()
    except Exception as e:
        log.error(f"Failed to start TradingBot: {e}")

if __name__ == "__main__":
    main()
