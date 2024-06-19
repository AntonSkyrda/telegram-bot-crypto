import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import F
from bit import PrivateKeyTestnet
from dotenv import load_dotenv
from database.database import SessionLocal, User
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State


load_dotenv()


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


API_TOKEN = os.getenv("BOT_TOKEN")


bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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
            key = PrivateKeyTestnet()
            user = User(telegram_id=user_id, priv_key=key.to_wif(), pub_key=key.address)
            db.add(user)
            db.commit()
            db.refresh(user)

        pub_key = user.pub_key
        await callback_query.message.answer(f"Ваш биткоин адрес (Testnet): {pub_key}")
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

        priv_key = user.priv_key
        key = PrivateKeyTestnet(priv_key)
        balance = key.get_balance("btc")

        if balance == 0:
            await callback_query.message.answer("Ваш баланс равен нулю.")
            await callback_query.answer()
            return

        await callback_query.message.answer(f"Ваш текущий баланс: {balance} BTC\nВведите адрес для вывода:")
        await state.set_state(WithdrawState.waiting_for_address)
        await callback_query.answer()


@dp.message(F.text, WithdrawState.waiting_for_address)
async def get_withdrawal_address(message: types.Message, state: FSMContext):
    withdrawal_address = message.text
    user_id = message.from_user.id

    with SessionLocal() as db:
        user = db.query(User).filter(User.telegram_id == user_id).first()
        priv_key = user.priv_key
        key = PrivateKeyTestnet(priv_key)
        balance = key.get_balance("btc")

        try:
            # Создание и отправка транзакции
            tx_hash = key.send([(withdrawal_address, balance, "btc")])
            await message.answer(f"Средства успешно отправлены!\nTx Hash: {tx_hash}")
        except Exception as e:
            await message.answer(f"Ошибка при выводе средств: {e}")

    await state.clear()


if __name__ == "__main__":
    import asyncio


    async def main():
        await dp.start_polling(bot)


    asyncio.run(main())
