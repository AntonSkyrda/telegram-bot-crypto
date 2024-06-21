import asyncio
import os
import logging
import uuid
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from database.database import SessionLocal, User
from tonclient.client import TonClient
from tonclient.types import (
    ClientConfig,
    NetworkConfig,
    ParamsOfQueryCollection,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_TOKEN = os.getenv("BOT_TOKEN")
EVERCLOUD_API_KEY = os.getenv("EVERCLOUD_API_KEY")

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

client = TonClient(config=ClientConfig(network=NetworkConfig(
    server_address="https://mainnet.ton.dev",
    endpoints=["https://mainnet.evercloud.dev/8ef464873ace4b81b48bd0ee4330b255/graphql"],
    access_key=EVERCLOUD_API_KEY
)))


# States definition
class WithdrawState(StatesGroup):
    waiting_for_address = State()


class TopUpState(StatesGroup):
    waiting_for_topup_amount = State()


# Generate TON address function
async def generate_ton_address():
    try:
        key_pair = client.crypto.generate_random_sign_keys()
        address = key_pair.public
        return address
    except Exception as e:
        logger.error(f"Error generating TON address: {e}")
        return None


# Handler for /start command
@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1. Пополнить", callback_data="top_up")],
        [InlineKeyboardButton(text="2. Вывести", callback_data="withdraw")]
    ])
    await message.answer("Выберите опцию:", reply_markup=keyboard)


def generate_payment_request_id():
    return str(uuid.uuid4())


@dp.callback_query(lambda c: c.data == "top_up")
async def process_top_up(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id

    # Generate a unique payment request
    payment_request = generate_payment_request_id()

    with SessionLocal() as db:
        user = db.query(User).filter(User.telegram_id == user_id).first()
        if not user:
            await callback_query.message.answer("Пользователь не найден.")
            await callback_query.answer()
            return

        await callback_query.message.answer(f"Для пополнения отправьте TON на адрес: {payment_request}")
        await callback_query.answer()


# Handler for withdraw callback query
@dp.callback_query(lambda c: c.data == "withdraw")
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
        balance_nano = int(balance_hex, 16)
        balance = balance_nano / 1e9

        if balance == 0:
            await callback_query.message.answer("Ваш баланс равен нулю.")
            await callback_query.answer()
            return

        await callback_query.message.answer(f"Ваш текущий баланс: {balance} TON\nВведите адрес для вывода:")
        await state.set_state(WithdrawState.waiting_for_address)
        await callback_query.answer()


async def get_withdrawal_address(message: types.Message, state: FSMContext):
    if message.from_user.id != state.data['user_id'] or state.state != WithdrawState.waiting_for_address:
        return

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


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")