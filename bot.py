import asyncio
import sqlite3
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

# --- НАСТРОЙКИ ---
BOT_TOKEN = "87...IU"  # Вставь сюда токен
ADMIN_ID = 9...5  # Вставь сюда свой Telegram ID (целое число, без кавычек)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# --- БАЗА ДАННЫХ ---
conn = sqlite3.connect('shop.db', check_same_thread=False)
cursor = conn.cursor()

# Создаем таблицы, если их нет
cursor.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 50,  
    referrer_id INTEGER,
    referral_bonus_claimed INTEGER DEFAULT 0  
)""")
cursor.execute("""CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    description TEXT,
    price INTEGER,
    quantity INTEGER DEFAULT 1,  
    file_id TEXT
)""")
cursor.execute("""CREATE TABLE IF NOT EXISTS cart (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    product_id INTEGER,
    quantity INTEGER DEFAULT 1  
)""")
conn.commit()

class AdminStates(StatesGroup):
    waiting_for_product_name = State()
    waiting_for_product_desc = State()
    waiting_for_product_price = State()
    waiting_for_product_quantity = State() # <-- ДОБАВИЛИ СОСТОЯНИЕ
    waiting_for_product_file = State()
    waiting_for_broadcast_message = State()
    waiting_for_restock_quantity = State()

class TopUpStates(StatesGroup):
    waiting_for_amount = State()


# --- КЛАВИАТУРЫ ---
def main_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🛍 Магазин", callback_data="shop")
    kb.button(text="🛒 Корзина", callback_data="view_cart")
    kb.button(text="💰 Баланс", callback_data="balance")
    kb.button(text="💳 Пополнить", callback_data="topup")
    kb.button(text="👥 Рефералка", callback_data="referral")
    if ADMIN_ID:
        kb.button(text="⚙️ Админка", callback_data="admin")
    kb.adjust(2, 2, 1, 1) # Расположение кнопок: 2 в ряд, потом 2, потом 1, потом 1
    return kb.as_markup()


# --- ХЭНДЛЕРЫ ПОЛЬЗОВАТЕЛЯ ---
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    # Извлекаем параметр из ссылки (если есть)
    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].isdigit():
        potential_ref = int(args[1])
        # Защита: нельзя быть рефералом самого себя
        if potential_ref != message.from_user.id:
            referrer_id = potential_ref

    # Проверяем, есть ли юзер в базе
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (message.from_user.id,))
    user_exists = cursor.fetchone()

    if not user_exists:
        # Регистрируем нового юзера с балансом 50 руб.
        cursor.execute("INSERT INTO users (user_id, balance, referrer_id, referral_bonus_claimed) VALUES (?, 50, ?, 0)",
                       (message.from_user.id, referrer_id))
        conn.commit()

        # Если он пришел по ссылке, сразу уведомляем пригласившего
        if referrer_id:
            try:
                await bot.send_message(
                    referrer_id,
                    f"👤 По вашей ссылке присоединился новый пользователь! Вы получите 100 руб. на баланс, как только он совершит первую покупку."
                )
            except:
                pass  # Если пригласивший заблокировал бота, игнорируем ошибку

    user_name = message.from_user.first_name or "друг"
    await message.answer(f"Привет, {user_name}! Я магазин цифровых товаров.",
                         reply_markup=main_menu_kb())

# --- ПОПОЛНЕНИЕ БАЛАНСА ---
@router.callback_query(F.data == "topup")
async def cb_topup(callback: CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="100 руб.", callback_data="topup_100")
    kb.button(text="500 руб.", callback_data="topup_500")
    kb.button(text="1000 руб.", callback_data="topup_1000")
    kb.button(text="✏️ Другая сумма", callback_data="topup_custom")
    kb.button(text="🔙 Назад", callback_data="back_to_menu")
    kb.adjust(3, 1, 1)
    try:
        await callback.message.edit_text("Выберите сумму пополнения (Тестовый режим: баланс пополнится мгновенно):",
                                         reply_markup=kb.as_markup())
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data.startswith("topup_"))
async def process_topup(callback: CallbackQuery, state: FSMContext):
    data = callback.data.split("_")[1]

    if data == "custom":
        await state.set_state(TopUpStates.waiting_for_amount)
        await callback.message.edit_text("Введите сумму пополнения (только число):")
        return

    amount = int(data)
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, callback.from_user.id))
    conn.commit()

    await callback.message.edit_text(f"✅ Баланс успешно пополнен на {amount} руб!", reply_markup=main_menu_kb())


@router.message(TopUpStates.waiting_for_amount)
async def process_custom_topup(message: Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) <= 0:
        await message.answer("Пожалуйста, введите положительное число!")
        return

    amount = int(message.text)
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, message.from_user.id))
    conn.commit()
    await state.clear()
    await message.answer(f"✅ Баланс успешно пополнен на {amount} руб!", reply_markup=main_menu_kb())


@router.callback_query(F.data == "balance")
async def cb_balance(callback: CallbackQuery):
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (callback.from_user.id,))
    balance = cursor.fetchone()[0]
    try:
        await callback.message.edit_text(f"Ваш баланс: {balance} руб.", reply_markup=main_menu_kb())
    except TelegramBadRequest:
        # Если сообщение не изменилось, просто отвечаем на саму кнопку (всплывающее окошко)
        await callback.answer("Вы уже смотрите этот раздел!")

@router.callback_query(F.data == "referral")
async def cb_referral(callback: CallbackQuery):
    link = f"https://t.me/{(await bot.me()).username}?start={callback.from_user.id}"
    text = (
        "👥 Реферальная программа:\n\n"
        f"1. Пригласи друга по ссылке:\n<code>{link}</code>\n\n"
        "2. Друг получит 50 руб. на баланс при регистрации.\n\n"
        "3. Ты получишь 100 руб. на баланс, как только твой друг совершит свою первую покупку!\n\n"
        "⚠️ Бонусы начисляются только за реальных пользователей."
    )
    try:
        await callback.message.edit_text(text, reply_markup=main_menu_kb(), parse_mode="HTML")
    except TelegramBadRequest:
        await callback.answer()


def get_product_card(product_id, user_id):
    cursor.execute("SELECT name, description, price, quantity FROM products WHERE id = ?", (product_id,))
    product = cursor.fetchone()
    if not product: return None, None

    name, desc, price, qty = product
    text = f"<b>{name}</b>\n\n📝 <b>Описание:</b>\n{desc or 'Нет описания.'}\n\n💰 <b>Цена:</b> {price} руб.\n"

    

    if qty <= 0:
        text += "🔴 <b>Нет в наличии</b>"
    else:
        text += f"🟢 <b>В наличии:</b> {qty} шт."

    # Проверяем корзину только для того, чтобы поменять текст кнопки
    cursor.execute("SELECT quantity FROM cart WHERE user_id = ? AND product_id = ?", (user_id, product_id))
    cart_item = cursor.fetchone()
    in_cart_qty = cart_item[0] if cart_item else 0

    kb = InlineKeyboardBuilder()
    if qty > 0:
        # Кнопка остается информативной
        btn_text = f"🛒 В корзине: {in_cart_qty} шт." if in_cart_qty > 0 else "🛒 Добавить в корзину"
        kb.button(text=btn_text, callback_data=f"add_to_cart_{product_id}")
    kb.button(text="🔙 Назад в магазин", callback_data="shop")
    kb.adjust(1)

    return text, kb.as_markup()


# 2. Магазин (Список товаров)
@router.callback_query(F.data == "shop")
async def cb_shop(callback: CallbackQuery):
    cursor.execute("SELECT id, name, price, quantity FROM products")
    products = cursor.fetchall()

    if not products:
        try:
            await callback.message.edit_text("Магазин пока пуст.", reply_markup=main_menu_kb())
        except TelegramBadRequest:
            await callback.answer("Магазин пуст.")
        return

    kb = InlineKeyboardBuilder()
    for prod in products:
        p_id, name, price, qty = prod
        btn_text = f"{name} - {price} руб." + (" (Нет в наличии)" if qty <= 0 else "")
        kb.button(text=btn_text, callback_data=f"info_{p_id}")

    kb.button(text="🔙 Назад", callback_data="back_to_menu")
    kb.adjust(1)

    try:
        await callback.message.edit_text("🛍 Выберите товар:", reply_markup=kb.as_markup())
    except TelegramBadRequest:
        await callback.answer()


# 3. Карточка товара (Описание)
@router.callback_query(F.data.startswith("info_"))
async def cb_product_info(callback: CallbackQuery):
    product_id = int(callback.data.split("_")[1])
    text, kb = get_product_card(product_id, callback.from_user.id)  # Передали user_id

    if not text:
        await callback.answer("Товар не найден.", show_alert=True)
        return

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data.startswith("add_to_cart_"))
async def cb_add_to_cart(callback: CallbackQuery):
    product_id = int(callback.data.split("_")[3])
    cursor.execute("SELECT name, quantity FROM products WHERE id = ?", (product_id,))
    product = cursor.fetchone()
    if not product: return

    name, stock_qty = product

    if stock_qty <= 0:
        await callback.answer("Этого товара сейчас нет в наличии!", show_alert=True)
        return

    cursor.execute("SELECT id, quantity FROM cart WHERE user_id = ? AND product_id = ?",
                   (callback.from_user.id, product_id))
    cart_item = cursor.fetchone()

    if cart_item:
        cart_id, current_cart_qty = cart_item
        new_qty = current_cart_qty + 1

        if new_qty > stock_qty:
            await callback.answer(f"На складе всего {stock_qty} шт.!", show_alert=True)
            return

        cursor.execute("UPDATE cart SET quantity = ? WHERE id = ?", (new_qty, cart_id))
    else:
        cursor.execute("INSERT INTO cart (user_id, product_id, quantity) VALUES (?, ?, 1)",
                       (callback.from_user.id, product_id))

    conn.commit()

    
    text, kb = get_product_card(product_id, callback.from_user.id)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass

    await callback.answer(f"✅ {name} добавлен в корзину!")


# 5. Просмотр корзины
@router.callback_query(F.data == "view_cart")
async def cb_view_cart(callback: CallbackQuery):
    cursor.execute("""SELECT cart.id, products.name, products.price, cart.quantity 
                      FROM cart JOIN products ON cart.product_id = products.id 
                      WHERE cart.user_id = ?""", (callback.from_user.id,))
    cart_items = cursor.fetchall()

    if not cart_items:
        try:
            await callback.message.edit_text("Ваша корзина пуста!", reply_markup=main_menu_kb())
        except TelegramBadRequest:
            await callback.answer("Корзина пуста!")
        return

    total_price = 0
    text = "🛒 Ваша корзина:\n\n"
    kb = InlineKeyboardBuilder()

    for item in cart_items:
        cart_id, name, price, qty = item
        item_sum = price * qty
        total_price += item_sum
        text += f"▪️ {name} (x{qty}) - {item_sum} руб.\n"
        kb.button(text=f"➖ Убрать 1 шт. {name}", callback_data=f"remove_{cart_id}")

    text += f"\n💰 Итого: {total_price} руб."

    kb.button(text="💳 Оформить заказ", callback_data="checkout")
    kb.button(text="🗑 Очистить корзину", callback_data="clear_cart")
    kb.button(text="🔙 Назад", callback_data="back_to_menu")
    kb.adjust(1)

    try:
        await callback.message.edit_text(text, reply_markup=kb.as_markup())
    except TelegramBadRequest:
        await callback.answer()


# 6. Удаление из корзины (Уменьшение количества)
@router.callback_query(F.data.startswith("remove_"))
async def cb_remove_from_cart(callback: CallbackQuery):
    cart_id = int(callback.data.split("_")[1])

    cursor.execute("SELECT quantity FROM cart WHERE id = ?", (cart_id,))
    item = cursor.fetchone()
    if not item:
        await cb_view_cart(callback)
        return

    current_qty = item[0]

    if current_qty > 1:
        cursor.execute("UPDATE cart SET quantity = quantity - 1 WHERE id = ?", (cart_id,))
    else:
        cursor.execute("DELETE FROM cart WHERE id = ?", (cart_id,))

    conn.commit()
    await callback.answer("Товар обновлен!")
    await cb_view_cart(callback)


@router.callback_query(F.data == "clear_cart")
async def cb_clear_cart(callback: CallbackQuery):
    cursor.execute("DELETE FROM cart WHERE user_id = ?", (callback.from_user.id,))
    conn.commit()
    await callback.answer("Корзина очищена!")
    await cb_view_cart(callback)


# 7. Оформление заказа (С проверкой остатков, списанием и рефералкой)
@router.callback_query(F.data == "checkout")
async def cb_checkout(callback: CallbackQuery):
    cursor.execute("SELECT cart.product_id, cart.quantity FROM cart WHERE cart.user_id = ?", (callback.from_user.id,))
    cart_items = cursor.fetchall()

    if not cart_items:
        await callback.answer("Корзина пуста!", show_alert=True)
        return

    total_price = 0
    valid_items = []
    invalid_items = []

    # 1. ПРОВЕРЯЕМ ОСТАТКИ ПЕРЕД ОПЛАТОЙ
    for item in cart_items:
        product_id, cart_qty = item
        cursor.execute("SELECT name, price, file_id, quantity FROM products WHERE id = ?", (product_id,))
        prod = cursor.fetchone()
        if not prod: continue

        name, price, file_id, stock_qty = prod

        if stock_qty < cart_qty:
            if stock_qty > 0:
                invalid_items.append(f"❌ '{name}' — осталось {stock_qty} шт., а у вас {cart_qty}.")
            else:
                invalid_items.append(f"❌ '{name}' — закончился!")
            cursor.execute("DELETE FROM cart WHERE user_id = ? AND product_id = ?", (callback.from_user.id, product_id))
        else:
            total_price += price * cart_qty
            valid_items.append({
                'product_id': product_id,
                'name': name,
                'file_id': file_id,
                'buy_qty': cart_qty
            })

    conn.commit()

    # 2. ЕСЛИ ЕСТЬ ТОВАРЫ, КОТОРЫЕ КОНЧИЛИСЬ
    if invalid_items:
        error_text = "⚠️ Проблема с остатками:\n\n" + "\n".join(invalid_items) + "\n\nМы убрали их из корзины."

        if valid_items:
            kb = InlineKeyboardBuilder()
            kb.button(text="💳 Оплатить оставшиеся", callback_data="checkout")
            kb.button(text="🏠 В главное меню", callback_data="back_to_menu")
            error_text += f"\n\nОстальные товары есть. Сумма: {total_price} руб."
            await callback.message.edit_text(error_text, reply_markup=kb.as_markup())
        else:
            await callback.message.edit_text(error_text + "\n\nКорзина пуста.", reply_markup=main_menu_kb())
        return

    # 3. ПРОВЕРЯЕМ БАЛАНС
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (callback.from_user.id,))
    balance = cursor.fetchone()[0]

    if balance < total_price:
        await callback.answer(f"Недостаточно средств! Нужно: {total_price} руб., у вас: {balance} руб.",
                              show_alert=True)
        return

    # 4. СПИСЫВАЕМ ДЕНЬГИ И ОСТАТКИ
    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (total_price, callback.from_user.id))
    cursor.execute("DELETE FROM cart WHERE user_id = ?", (callback.from_user.id,))

    for item in valid_items:
        cursor.execute("UPDATE products SET quantity = quantity - ? WHERE id = ?",
                       (item['buy_qty'], item['product_id']))

    # --- РЕФЕРАЛЬНАЯ СИСТЕМА ---
    cursor.execute("SELECT referrer_id, referral_bonus_claimed FROM users WHERE user_id = ?", (callback.from_user.id,))
    ref_data = cursor.fetchone()

    if ref_data and ref_data[0] and ref_data[1] == 0:
        ref_id = ref_data[0]
        cursor.execute("UPDATE users SET balance = balance + 100 WHERE user_id = ?", (ref_id,))
        cursor.execute("UPDATE users SET referral_bonus_claimed = 1 WHERE user_id = ?", (callback.from_user.id,))
        try:
            await bot.send_message(ref_id, "🎉 Ваш реферал совершил первую покупку! Вам начислено 100 руб.")
        except:
            pass

    conn.commit()

    # 5. ВЫДАЕМ ТОВАРЫ
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 В главное меню", callback_data="back_to_menu")

    await callback.message.edit_text(f"✅ Заказ оплачен! Списано {total_price} руб. Товары отправлены ниже:",
                                     reply_markup=kb.as_markup())

    for item in valid_items:
        name, file_id, qty = item['name'], item['file_id'], item['buy_qty']

        # Получаем актуальный остаток на складе ПОСЛЕ списания
        cursor.execute("SELECT quantity FROM products WHERE id = ?", (item['product_id'],))
        new_stock = cursor.fetchone()[0]

        # Формируем красивый заголовок
        text_header = f"📦 <b>{name}</b>\n🛒 Куплено: {qty} шт. | 🏪 Остаток на складе: {new_stock} шт."

        if file_id:
            if len(file_id) > 50:
                await callback.message.answer_document(document=file_id, caption=text_header, parse_mode="HTML")
            else:
                await callback.message.answer(f"{text_header}\n\n🎁 Данные:\n<code>{file_id}</code>", parse_mode="HTML")
        else:
            await callback.message.answer(f"{text_header}\n(Без файла/ссылки)", parse_mode="HTML")


@router.callback_query(F.data == "back_to_menu")
async def cb_back(callback: CallbackQuery):
    await callback.message.edit_text("Главное меню:", reply_markup=main_menu_kb())


# --- ХЭНДЛЕРЫ АДМИНКИ ---
@router.callback_query(F.data == "admin")
async def cb_admin(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить товар", callback_data="admin_add")
    kb.button(text="🗑 Удалить товар", callback_data="admin_delete") # <-- ДОБАВИЛИ
    kb.button(text="♻️ Пополнить остатки", callback_data="admin_restock")  # <--- ДОБАВИЛИ
    kb.button(text="📢 Рассылка", callback_data="admin_broadcast")
    kb.button(text="🔙 Назад", callback_data="back_to_menu")
    kb.adjust(1)
    try:
        await callback.message.edit_text("Панель администратора:", reply_markup=kb.as_markup())
    except TelegramBadRequest:
        await callback.answer()

@router.callback_query(F.data == "admin_add")
async def cb_admin_add(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.set_state(AdminStates.waiting_for_product_name)
    await callback.message.edit_text("Введите название товара:")


@router.callback_query(F.data == "admin_restock")
async def cb_admin_restock(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return

    cursor.execute("SELECT id, name, quantity FROM products")
    products = cursor.fetchall()

    if not products:
        await callback.answer("Нет товаров для пополнения!", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    for prod in products:
        kb.button(text=f"📦 {prod[1]} (Остаток: {prod[2]})", callback_data=f"restock_{prod[0]}")
    kb.button(text="🔙 Назад", callback_data="admin")
    kb.adjust(1)

    try:
        await callback.message.edit_text("Выберите товар, остатки которого хотите пополнить:",
                                         reply_markup=kb.as_markup())
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data.startswith("restock_"))
async def cb_select_restock_product(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return

    product_id = int(callback.data.split("_")[1])
    cursor.execute("SELECT name FROM products WHERE id = ?", (product_id,))
    product = cursor.fetchone()
    if not product: return

    # Сохраняем ID товара, который будем пополнять, в стейт
    await state.update_data(restock_product_id=product_id)
    await state.set_state(AdminStates.waiting_for_restock_quantity)
    await callback.message.edit_text(f"Введите количество для добавления к товару '{product[0]}':")


@router.message(AdminStates.waiting_for_restock_quantity)
async def process_restock_quantity(message: Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) <= 0:
        await message.answer("Пожалуйста, введите положительное число!")
        return

    amount = int(message.text)
    data = await state.get_data()
    product_id = data.get('restock_product_id')

    if not product_id:
        await state.clear()
        await message.answer("Ошибка, попробуйте снова.", reply_markup=main_menu_kb())
        return

    # ДОБАВЛЯЕМ количество к текущему остатку
    cursor.execute("UPDATE products SET quantity = quantity + ? WHERE id = ?", (amount, product_id))
    conn.commit()
    await state.clear()

    kb = InlineKeyboardBuilder()
    kb.button(text="♻️ Пополнить еще", callback_data="admin_restock")
    kb.button(text="⚙️ В админку", callback_data="admin")
    kb.button(text="🏠 В главное меню", callback_data="back_to_menu")
    kb.adjust(1)

    await message.answer(f"✅ Остаток успешно пополнен на {amount} шт!", reply_markup=kb.as_markup())


@router.callback_query(F.data == "admin_delete")
async def cb_admin_delete(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return

    cursor.execute("SELECT id, name FROM products")
    products = cursor.fetchall()

    if not products:
        await callback.answer("Нет товаров для удаления!", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    for prod in products:
        kb.button(text=f"❌ {prod[1]}", callback_data=f"delprod_{prod[0]}")
    kb.button(text="🔙 Назад", callback_data="admin")
    kb.adjust(1)

    try:
        await callback.message.edit_text("Выберите товар для удаления:", reply_markup=kb.as_markup())
    except TelegramBadRequest:
        await callback.answer()


@router.callback_query(F.data.startswith("delprod_"))
async def cb_delete_product(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return

    product_id = int(callback.data.split("_")[1])
    # Удаляем товар из таблицы товаров
    cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
    # ВАЖНО: Удаляем товар из корзин всех пользователей, чтобы не было ошибок
    cursor.execute("DELETE FROM cart WHERE product_id = ?", (product_id,))
    conn.commit()

    await callback.answer("Товар удален!", show_alert=True)
    
    await cb_admin_delete(callback)

@router.message(AdminStates.waiting_for_product_name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AdminStates.waiting_for_product_desc)
    await message.answer("Введите описание товара:")


@router.message(AdminStates.waiting_for_product_desc)
async def process_desc(message: Message, state: FSMContext):
    await state.update_data(desc=message.text)
    await state.set_state(AdminStates.waiting_for_product_price)
    await message.answer("Введите цену товара (только число):")


@router.message(AdminStates.waiting_for_product_price)
async def process_price(message: Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) <= 0:
        await message.answer("Цена должна быть положительным числом!")
        return
    await state.update_data(price=int(message.text))
    await state.set_state(AdminStates.waiting_for_product_quantity)  # <-- ПЕРЕХОД К КОЛИЧЕСТВУ
    await message.answer("Введите количество товара (число):")


@router.message(AdminStates.waiting_for_product_quantity)
async def process_quantity(message: Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) < 0:
        await message.answer("Количество должно быть числом (0 или больше)!")
        return
    await state.update_data(quantity=int(message.text))
    await state.set_state(AdminStates.waiting_for_product_file)
    await message.answer("Отправьте файл товара (документ) или напишите 'нет':")


@router.message(AdminStates.waiting_for_product_file, F.document | F.text)
async def process_file(message: Message, state: FSMContext):
    payload = None
    is_file = False  # Флаг, чтобы понять, файл это или текст/ссылка

    if message.document:
        payload = message.document.file_id
        is_file = True
    elif message.text and message.text.lower() != 'нет':
        # Теперь мы сохраняем ЛЮБОЙ текст, а не только то, что начинается на http
        # Это может быть ссылка, ключ активации, логин-пароль и т.д.
        payload = message.text
    else:
        payload = None

    data = await state.get_data()

    # Сохраняем в БД
    cursor.execute("INSERT INTO products (name, description, price, quantity, file_id) VALUES (?, ?, ?, ?, ?)",
                   (data['name'], data['desc'], data['price'], data.get('quantity', 1), payload))
    conn.commit()
    await state.clear()

    # Клавиатура после добавления
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить еще", callback_data="admin_add")
    kb.button(text="⚙️ В админку", callback_data="admin")
    kb.button(text="🏠 В главное меню", callback_data="back_to_menu")
    kb.adjust(1)

    if is_file:
        await message.answer("✅ Товар (файл) успешно добавлен!", reply_markup=kb.as_markup())
    elif payload:
        await message.answer("✅ Товар (ссылка/код) успешно добавлен!", reply_markup=kb.as_markup())
    else:
        await message.answer("✅ Товар (без файла/ссылки) добавлен!", reply_markup=kb.as_markup())

@router.callback_query(F.data == "admin_broadcast")
async def cb_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.set_state(AdminStates.waiting_for_broadcast_message)
    await callback.message.edit_text("Введите текст для рассылки всем пользователям:\n(или нажмите /cancel для отмены)")

@router.message(AdminStates.waiting_for_broadcast_message)
async def process_broadcast(message: Message, state: FSMContext):
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    success = 0
    for user in users:
        try:
            await bot.send_message(user[0], message.text)
            success += 1
        except:
            pass
    await state.clear()

    kb = InlineKeyboardBuilder()
    kb.button(text="⚙️ В админку", callback_data="admin")
    kb.button(text="🏠 В главное меню", callback_data="back_to_menu")
    kb.adjust(1)

    await message.answer(f"✅ Рассылка завершена. Доставлено: {success}/{len(users)}", reply_markup=kb.as_markup())

# --- БЕЗОПАСНАЯ ГЛОБАЛЬНАЯ РАССЫЛКА ---
async def broadcast_all(text, **kwargs):
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    for user in users:
        try:
            # Передаем kwargs (в котором лежит parse_mode="HTML") в send_message
            await bot.send_message(user[0], text, **kwargs)
            await asyncio.sleep(0.05) # Обязательная задержка
        except Exception:
            pass


async def on_startup(bot: Bot):
    
    await asyncio.sleep(2)
    await broadcast_all("✅ <b>Бот возобновил работу!</b>\n\nДля продолжения нажмите /start", parse_mode="HTML")

async def on_shutdown(bot: Bot):
    await broadcast_all("⚠️ <b>Бот временно не работает</b>\n\nМы проводим технические работы. Скоро вернемся!", parse_mode="HTML")
    # закрываем соединение с базой данных при выключении
    conn.close()


async def main():
    # РЕГИСТРИРУЕМ ХУКИ
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
