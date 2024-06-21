import asyncio
import os
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from database.database import SessionLocal, User
from tonclient.client import TonClient, ClientConfig
from tonclient.types import NetworkConfig, ParamsOfQueryCollection

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_TOKEN = os.getenv("BOT_TOKEN")
EVERCLOUD_API_KEY = os.getenv("EVERCLOUD_API_KEY")

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

client = TonClient(config=ClientConfig(network=NetworkConfig(
    server_address="https://devnet.ton.dev",  # Для DevNet
    endpoints=["https://devnet.evercloud.dev/8ef464873ace4b81b48bd0ee4330b255/graphql"],
    access_key=EVERCLOUD_API_KEY
)))


class WithdrawState(StatesGroup):
    waiting_for_address = State()


@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1. Пополнить", callback_data="top_up")],
        [InlineKeyboardButton(text="2. Вывести", callback_data="withdraw")]
    ])
    await message.answer("Выберите опцию:", reply_markup=keyboard)


@dp.callback_query(F.data == "top_up")
async def process_top_up(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id

    with SessionLocal() as db:
        user = db.query(User).filter(User.telegram_id == user_id).first()
        if not user:
            # Assuming you have some logic to generate a TON address
            # Replace the below line with the correct logic to generate the address
            address = "Generated_TON_Address"
            user = User(telegram_id=user_id, pub_key=address)
            db.add(user)
            db.commit()
            db.refresh(user)

        pub_key = user.pub_key
        await callback_query.message.answer(f"Ваш TON адрес: {pub_key}")
        await callback_query.answer()


@dp.callback_query(F.data == "withdraw")
async def process_withdraw(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id

    with SessionLocal() as db:
        user = db.query(User).filter(User.telegram_id == user_id).first()
        if not user:
            await callback_query.message.answer("Сначала пополните ваш счет.")
            await callback_query.answer()
            return

        pub_key = user.pub_key

        params = ParamsOfQueryCollection(
            collection="accounts",
            filter={"id": {"eq": pub_key}},
            result="balance"
        )

        balance_result = client.net.query_collection(params=params)

        balance_hex = balance_result.result[0]["balance"]
        balance_nano = int(balance_hex, 16)  # Конвертуємо з шістнадцяткового у десятковий формат
        balance = balance_nano / 1e9  # Конвертуємо з nano у звичайні TON

        if balance == 0:
            await callback_query.message.answer("Ваш баланс равен нулю.")
            await callback_query.answer()
            return

        await callback_query.message.answer(f"Ваш текущий баланс: {balance} TON\nВведите адрес для вывода:")
        await state.set_state(WithdrawState.waiting_for_address)
        await callback_query.answer()


@dp.message(F.text, WithdrawState.waiting_for_address)
async def get_withdrawal_address(message: types.Message, state: FSMContext):
    withdrawal_address = message.text
    user_id = message.from_user.id

    with SessionLocal() as db:
        user = db.query(User).filter(User.telegram_id == user_id).first()
        pub_key = user.pub_key

        params = ParamsOfQueryCollection(
            collection="accounts",
            filter={"id": {"eq": pub_key}},
            result="balance"
        )

        balance_result = client.net.query_collection(params=params)
        balance_hex = balance_result.result[0]["balance"]
        balance_nano = int(balance_hex, 16)
        balance = balance_nano / 1e9

        try:
            tx_hash = "Generated_Transaction_Hash"
            await message.answer(f"Средства успешно отправлены!\nTx Hash: {tx_hash}")
        except Exception as e:
            await message.answer(f"Ошибка при выводе средств: {e}")

    await state.clear()


if __name__ == "__main__":
    try:
        async def main():
            await dp.start_polling(bot)

        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
