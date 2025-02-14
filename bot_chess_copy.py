import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import ParseMode, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from openpyxl import load_workbook
import os
import time

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8"
)

# Инициализация бота
API_TOKEN = ''  # Замените на ваш токен
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Файлы для сохранения данных
PROGRESS_FILE = "user_progress.txt"
BANS_FILE = "user_bans.txt"
USERS_FILE = "users.txt"  # Файл для хранения ID пользователей и их статусов
BROADCAST_TEMPLATE_FILE = "broadcast_template.txt"  # Файл для хранения шаблона рассылки

# Глобальные переменные
ADMIN_IDS = [1881684121, 5312321185]  # 5312321185 Rus 1881684121
groups_data = []  # Все группы
sent_groups = {}  # Отправленные группы: {user_id: [group_index1, group_index2, ...]}
current_group_index = {}  # Текущая группа для каждого пользователя: {user_id: current_index}
user_bans = {}  # Блокировки пользователей: {user_id: ban_time}
users_status = {}  # Статусы пользователей: {user_id: status}
# Глобальная переменная для хранения никнеймов пользователей
user_nicknames = {}  # {user_id: nickname}

# Очередь для отправки сообщений администраторам
message_queue = asyncio.Queue()

# Задержка между отправками сообщений (в секундах)
SEND_DELAY = 1

async def process_message_queue():
    while True:
        # Получаем сообщение из очереди
        chat_id, message_text, media = await message_queue.get()
        try:
            if media:
                # Если есть медиафайлы, отправляем медиагруппу
                await bot.send_media_group(chat_id=chat_id, media=media)
                logging.info(f"Медиагруппа отправлена админу {chat_id}.")
            else:
                # Если нет медиафайлов, отправляем текстовое сообщение
                await bot.send_message(chat_id=chat_id, text=message_text)
                logging.info(f"Текстовое сообщение отправлено админу {chat_id}.")
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения админу {chat_id}: {e}")
        finally:
            # Добавляем задержку между отправками
            await asyncio.sleep(SEND_DELAY)
            # Помечаем задачу как выполненную
            message_queue.task_done()

# Глобальная переменная для отслеживания текущей группы
global_group_index = 0

def load_data():
    global sent_groups, current_group_index, user_bans, users_status, global_group_index
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) >= 2:  # Убедимся, что строка содержит хотя бы user_id и group_indices
                    user_id = parts[0]
                    group_indices = parts[1:]
                    try:
                        # Преобразуем user_id в int
                        user_id = int(user_id)
                        # Фильтруем только числовые значения для group_indices
                        valid_indices = [int(index) for index in group_indices if index.isdigit()]
                        sent_groups[user_id] = valid_indices
                        current_group_index[user_id] = valid_indices[-1] if valid_indices else -1  # Последний индекс отправленной группы
                    except ValueError as e:
                        logging.error(f"Ошибка при загрузке данных из строки: {line.strip()}. Ошибка: {e}")
                        continue  # Пропускаем некорректные строки
        # Определяем максимальный индекс группы среди всех пользователей
        if sent_groups:  # Проверяем, что sent_groups не пуст
            max_group_index = max((max(indices) for indices in sent_groups.values()), default=0)
            global_group_index = max_group_index + 1  # Устанавливаем глобальный индекс на следующую группу
        else:
            global_group_index = 0  # Если sent_groups пуст, начинаем с нуля
    else:
        global_group_index = 0  # Если файла нет, начинаем с нуля

    if os.path.exists(BANS_FILE):
        with open(BANS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) == 2:  # Убедимся, что строка содержит user_id и ban_time
                    user_id, ban_time = parts
                    try:
                        user_bans[int(user_id)] = float(ban_time)
                    except ValueError as e:
                        logging.error(f"Ошибка при загрузке блокировки из строки: {line.strip()}. Ошибка: {e}")

    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(",", 1)  # Разделяем по первой запятой
                if len(parts) == 2:  # Убедимся, что строка содержит user_id и status
                    user_id, status = parts
                    try:
                        users_status[int(user_id)] = status
                    except ValueError as e:
                        logging.error(f"Ошибка при загрузке статуса из строки: {line.strip()}. Ошибка: {e}")

# Сохранение данных в файлы
def save_data():
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        for user_id, group_indices in sent_groups.items():
            f.write(f"{user_id},{','.join(map(str, group_indices))}\n")
    with open(BANS_FILE, "w", encoding="utf-8") as f:
        for user_id, ban_time in user_bans.items():
            f.write(f"{user_id},{ban_time}\n")
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        for user_id, status in users_status.items():
            f.write(f"{user_id},{status}\n")

# Проверка блокировки пользователя
def is_user_banned(user_id):
    if user_id in user_bans:
        # Проверяем, истекло ли время блокировки
        if time.time() < user_bans[user_id]:
            return True
        else:
            # Удаляем блокировку, если время истекло
            del user_bans[user_id]
            users_status[user_id] = ""  # Сбрасываем статус
            save_data()
    return False

# Клавиатура для пользователей
def get_user_keyboard():
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("Получить следующую группу", callback_data="get_next_group"),
        InlineKeyboardButton("Получил бан", callback_data="ban_user")
    )
    # Добавляем новую кнопку "Шаблон рассылки"
    keyboard.row(
        InlineKeyboardButton("Шаблон рассылки", callback_data="show_broadcast_template")
    )
    # Добавляем кнопку "Инструкция"
    keyboard.row(
        InlineKeyboardButton("Инструкция", callback_data="send_instruction")
    )
    return keyboard

# Клавиатура для изменения статуса пользователя
def get_admin_keyboard(user_id):
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("❌", callback_data=f"set_status:{user_id}:❌"),
        InlineKeyboardButton("✅", callback_data=f"set_status:{user_id}:✅"),
        InlineKeyboardButton("Очистить", callback_data=f"set_status:{user_id}:")
    )
    # Добавляем кнопку "Снять бан"
    keyboard.row(
        InlineKeyboardButton("Снять бан", callback_data=f"remove_ban:{user_id}")
    )
    return keyboard

# Клавиатура для администраторов
def get_admin_panel():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)  # Используем ReplyKeyboardMarkup
    keyboard.add(KeyboardButton("/run"), KeyboardButton("/send_groups"))
    keyboard.add(KeyboardButton("/users"), KeyboardButton("Изменить шаблон"))
    return keyboard

# Клавиатура для списка пользователей
def get_users_list_keyboard():
    keyboard = InlineKeyboardMarkup()
    for user_id, status in users_status.items():
        # Если никнейма нет, не добавляем его в текст кнопки
        nickname = user_nicknames.get(user_id, "")  # Получаем ник или пустую строку
        if nickname:
            button_text = f"ID: {user_id} | Ник: {nickname} | Статус: {status or 'Без статуса'}"
        else:
            button_text = f"ID: {user_id} | Статус: {status or 'Без статуса'}"
        keyboard.add(InlineKeyboardButton(button_text, callback_data=f"user_select:{user_id}"))
    return keyboard

# Загрузка шаблона рассылки
def load_broadcast_template():
    if os.path.exists(BROADCAST_TEMPLATE_FILE):
        with open(BROADCAST_TEMPLATE_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return (
        "Hello! We invite your university team ([вставить название вуза в скобках]) to participate in the 8th Interuniversity Team Battle, "
        "the largest interuniversity online tournament on Lichess.\n\n"
        "📅 Date & Time: February 23, 2025 – 12:00 UTC\n"
        "⏳ Time Control: 3+0 Blitz, Rated\n"
        "🔗 Tournament Link: https://lichess.org/tournament/2OVexrSo\n\n"
        "1st Hunger Games – March 23, 2025 |Unique Format|\n"
        "https://lichess.org/tournament/oHZ8MI8c\n\n"
        "9th Interuniversity Team Battle – March 30, 2025 |3+3 Chess960|\n"
        "https://lichess.org/tournament/R9VQU47N\n\n"
        "10th Interuniversity Team Battle – April 27, 2025 |5+0 Blitz|\n"
        "https://lichess.org/tournament/dKuocHFV\n\n"
        "Participation is free and open to all university teams. Feel free to share this invitation with your club members. "
        "We look forward to seeing your team compete!\n\n"
        "Best regards,\n"
        "[вставить ваше имя]\n"
        "Interuniversity Team Battles Coordinator"
    )

# Сохранение шаблона рассылки
def save_broadcast_template(template_text):
    with open(BROADCAST_TEMPLATE_FILE, "w", encoding="utf-8") as f:
        f.write(template_text)

# Обработка Excel-файла и создание групп
def process_excel():
    logging.info("Читаем данные из Excel и формируем группы...")
    filename = 'lichess_club_admins.xlsx'
    workbook = load_workbook(filename)
    sheet = workbook.active
    af_column_index = 32  # AF
    data = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        club_url = row[0]
        active_admins = row[af_column_index - 1]
        data.append((club_url, active_admins))
    # Сортируем данные по убыванию количества активных администраторов
    data_sorted = sorted(data, key=lambda x: x[1], reverse=True)
    # Каждая группа — это одна ссылка клуба
    groups = [[club] for club in data_sorted]
    logging.info(f"Создано {len(groups)} групп")
    return groups

# Функция для создания групп
def create_group(data_sorted, group_size, target_sum):
    current_group = []
    current_sum = 0
    removed_indices = []
    for i, (club_url, admins) in enumerate(data_sorted):
        if len(current_group) < group_size and current_sum + admins <= target_sum:
            current_group.append((club_url, admins))
            current_sum += admins
            removed_indices.append(i)
        if len(current_group) == group_size or current_sum >= target_sum:
            break
    data_sorted = [item for i, item in enumerate(data_sorted) if i not in removed_indices]
    return current_group, data_sorted

# Автоматическое восстановление блокировки через 24 часа
async def restore_ban_if_inactive(user_id):
    await asyncio.sleep(24 * 60 * 60)  # Ждем 24 часа
    if user_id not in user_bans and user_id in users_status:
        # Проверяем, был ли пользователь активен за последние 24 часа
        if is_user_banned(user_id):
            return  # Пользователь уже заблокирован

        # Блокируем пользователя снова
        user_bans[user_id] = time.time() + 24 * 60 * 60  # Блокировка на 24 часа
        users_status[user_id] = ""  # Сбрасываем статус
        save_data()

        try:
            await bot.send_message(
                user_id,
                "Вы были автоматически заблокированы, так как не взаимодействовали с ботом в течение 24 часов."
            )
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")

# Команда /start
@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    user_id = message.from_user.id

    # Проверяем, является ли пользователь верифицированным
    if user_id not in ADMIN_IDS and user_id not in users_status:
        await message.reply("У вас нет доступа к этому боту.")
        return

    # Проверяем блокировку пользователя
    if is_user_banned(user_id):
        # Если пользователь заблокирован, отправляем сообщение и завершаем обработку
        await message.reply("Вы заблокированы. Вернитесь через 24 часа.")
        return

    # Логика для администраторов
    if user_id in ADMIN_IDS:
        await message.reply(
            "Привет, администратор! Вот ваша панель управления:",
            reply_markup=get_admin_panel()
        )
    else:
        # Для обычных пользователей
        keyboard = get_user_keyboard()
        await message.reply(
            "Привет! Нажмите кнопку ниже, чтобы получить группу.",
            reply_markup=keyboard
        )

# Команда /run (для администраторов)
@dp.message_handler(commands=['run'])
async def run_script(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("У вас нет прав для выполнения этой команды.")
        return
    await message.answer("Запускаю скрипт... Пожалуйста, подождите.")
    try:
        global groups_data
        groups_data = process_excel()
        await message.answer(f"Группы успешно созданы. Всего групп: {len(groups_data)}")
    except Exception as e:
        logging.error(f"Произошла ошибка: {e}")
        await message.answer(f"Произошла ошибка: {str(e)}", parse_mode=None)

# Команда /send_groups (для администраторов)
@dp.message_handler(commands=['send_groups'])
async def send_groups(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("У вас нет прав для выполнения этой команды.")
        return
    if not groups_data:
        await message.answer("Группы еще не созданы. Сначала выполните команду /run.")
        return
    await message.answer("Готово! Пользователи могут начать получать группы.")

# Команда /users (для администраторов)
@dp.message_handler(commands=['users'])
async def list_users(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("У вас нет прав для выполнения этой команды.")
        return
    if not users_status:
        await message.answer("Нет зарегистрированных пользователей.")
        return
    await message.answer("Список пользователей:", reply_markup=get_users_list_keyboard())
# Словарь для отслеживания состояний администраторов
admin_states = {}  # {user_id: state}

# Обработка кнопки "Изменить шаблон"
@dp.message_handler(lambda message: message.text == "Изменить шаблон")
async def change_broadcast_template(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("У вас нет прав для выполнения этого действия.")
        return
    # Переводим администратора в состояние ожидания нового шаблона
    admin_states[user_id] = "waiting_for_template"
    await message.answer("Пожалуйста, отправьте новый текст шаблона.")

# Обработка нового шаблона
@dp.message_handler(lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id] == "waiting_for_template")
async def update_broadcast_template(message: types.Message):
    user_id = message.from_user.id
    new_template = message.text
    # Сохраняем новый шаблон в файл
    save_broadcast_template(new_template)
    # Удаляем состояние администратора
    del admin_states[user_id]
    await message.answer("Шаблон успешно обновлен!")

# Обработка кнопки "Шаблон рассылки"
@dp.callback_query_handler(lambda c: c.data == "show_broadcast_template")
async def show_broadcast_template(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    # Загружаем текущий шаблон
    template_text = load_broadcast_template()
    # Клавиатура с кнопкой возврата
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("Вернуться в меню", callback_data="return_to_menu")
    )
    # Отправляем шаблон текста и клавиатуру
    await bot.send_message(user_id, template_text, reply_markup=keyboard)
    # Удаляем старое сообщение с кнопками
    await bot.delete_message(chat_id=user_id, message_id=callback_query.message.message_id)

# Обработка кнопки "Вернуться в меню"
@dp.callback_query_handler(lambda c: c.data == "return_to_menu")
async def return_to_menu(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id

    # Отправляем главное меню
    keyboard = get_user_keyboard()
    await bot.send_message(user_id, "Вы вернулись в главное меню.", reply_markup=keyboard)

    # Удаляем старое сообщение с кнопками
    await bot.delete_message(chat_id=user_id, message_id=callback_query.message.message_id)

# Обработка кнопки "Инструкция"
@dp.callback_query_handler(lambda c: c.data == "send_instruction")
async def send_instruction(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id

    # Путь к файлу инструкции (предполагается, что файл лежит в папке проекта)
    instruction_file = "Инструкция.pdf"

    # Проверяем, существует ли файл
    if not os.path.exists(instruction_file):
        await bot.send_message(user_id, "Извините, инструкция временно недоступна.")
        return

    # Клавиатура с кнопкой возврата
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("Вернуться в меню", callback_data="return_to_menu")
    )

    # Отправляем PDF-файл
    with open(instruction_file, "rb") as file:
        await bot.send_document(
            chat_id=user_id,
            document=file,
            caption="Инструкция по использованию бота и рассылке.",
            reply_markup=keyboard
        )

    # Удаляем старое сообщение с кнопками
    await bot.delete_message(chat_id=user_id, message_id=callback_query.message.message_id)

# Обработка кнопки "Снять бан"
@dp.callback_query_handler(lambda c: c.data.startswith("remove_ban:"))
async def remove_ban(callback_query: types.CallbackQuery):
    admin_id = callback_query.from_user.id
    if admin_id not in ADMIN_IDS:
        await bot.answer_callback_query(callback_query.id, "У вас нет прав для выполнения этого действия.")
        return

    _, user_id = callback_query.data.split(":")
    user_id = int(user_id)

    # Проверяем, заблокирован ли пользователь
    if user_id not in user_bans:
        await bot.answer_callback_query(callback_query.id, "Пользователь не заблокирован.")
        return

    # Снимаем блокировку
    del user_bans[user_id]
    save_data()

    # Отправляем уведомление пользователю
    try:
        await bot.send_message(
            user_id,
            "Администратор снял вашу блокировку. Вы можете продолжить получать группы.",
            reply_markup=get_user_keyboard()
        )
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
        await bot.answer_callback_query(callback_query.id, "Не удалось отправить уведомление пользователю.")
        return

    # Уведомляем администратора
    await bot.edit_message_text(
        chat_id=admin_id,
        message_id=callback_query.message.message_id,
        text=f"Блокировка пользователя {user_id} успешно снята."
    )

    # Запускаем таймер на 24 часа
    asyncio.create_task(restore_ban_if_inactive(user_id))

# Обработка выбора пользователя
@dp.callback_query_handler(lambda c: c.data.startswith("user_select:"))
async def select_user(callback_query: types.CallbackQuery):
    admin_id = callback_query.from_user.id
    if admin_id not in ADMIN_IDS:
        await bot.answer_callback_query(callback_query.id, "У вас нет прав для выполнения этого действия.")
        return
    _, user_id = callback_query.data.split(":")
    user_id = int(user_id)
    await bot.edit_message_text(
        chat_id=admin_id,
        message_id=callback_query.message.message_id,
        text=f"Выбран пользователь ID: {user_id}. Измените его статус:",
        reply_markup=get_admin_keyboard(user_id)
    )

# Изменение статуса пользователя
@dp.callback_query_handler(lambda c: c.data.startswith("set_status:"))
async def set_user_status(callback_query: types.CallbackQuery):
    admin_id = callback_query.from_user.id
    if admin_id not in ADMIN_IDS:
        await bot.answer_callback_query(callback_query.id, "У вас нет прав для выполнения этого действия.")
        return
    _, user_id, status = callback_query.data.split(":")
    user_id = int(user_id)
    users_status[user_id] = status
    save_data()
    await bot.edit_message_text(
        chat_id=admin_id,
        message_id=callback_query.message.message_id,
        text=f"Статус пользователя {user_id} изменен на: {status or 'Без статуса'}",
        reply_markup=get_admin_keyboard(user_id)
    )

# Обработка кнопки "Получить следующую группу"
@dp.callback_query_handler(lambda c: c.data == "get_next_group")
async def get_next_group(callback_query: types.CallbackQuery):
    global global_group_index  # Используем глобальный счетчик
    user_id = callback_query.from_user.id

    # Проверяем, есть ли группы для отправки
    if not groups_data:
        await bot.answer_callback_query(callback_query.id, "Группы еще не созданы. Сначала выполните команду /run.")
        return

    # Получаем индекс текущей группы для пользователя
    if user_id in current_group_index:
        group_index = current_group_index[user_id] + 1  # Начинаем со следующей группы
    else:
        group_index = global_group_index  # Если пользователь новый, используем глобальный индекс

    # Проверяем, остались ли группы для отправкиs
    if group_index >= len(groups_data):
        group_index = 0  # Сбрасываем счетчик, если достигнут конец списка групп
        await bot.answer_callback_query(callback_query.id, "Группы закончились. Начинаем сначала.")

    # Получаем группу
    group = groups_data[group_index]

    # Формируем сообщение с информацией о группе
    club_url, active_admins = group[0]
    group_message = f"{club_url} ({active_admins} активных админов)"
    await bot.send_message(user_id, f"Ваша группа:\n{group_message}")

    # Обновляем данные о отправленных группах
    if user_id not in sent_groups:
        sent_groups[user_id] = []
    sent_groups[user_id].append(group_index)
    current_group_index[user_id] = group_index  # Обновляем текущий индекс для пользователя
    save_data()

    # Увеличиваем глобальный счетчик для следующего пользователя
    global_group_index = max(global_group_index, group_index + 1)

    # Удаляем старое сообщение с кнопкой
    await bot.delete_message(chat_id=user_id, message_id=callback_query.message.message_id)

    # Отправляем новую клавиатуру
    await bot.send_message(user_id, "Что дальше?", reply_markup=get_user_keyboard())

# Обработка кнопки "Получил бан"
@dp.callback_query_handler(lambda c: c.data == "ban_user")
async def ban_user(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id

    # Проверяем, зарегистрирован ли пользователь
    if user_id not in users_status:
        await bot.answer_callback_query(callback_query.id, "У вас нет доступа к этому действию.")
        return

    # Удаляем старое сообщение с кнопкой
    await bot.delete_message(chat_id=user_id, message_id=callback_query.message.message_id)

    # Блокируем пользователя на 24 часа
    ban_time = time.time() + 24 * 60 * 60  # 24 часа
    user_bans[user_id] = ban_time
    users_status[user_id] = ""  # Сбрасываем статус
    save_data()

    await bot.send_message(user_id, "Вы заблокированы. Вернитесь через 24 часа.")

# Словарь для временного хранения медиагрупп
media_groups = {}
# Словарь для отслеживания обработанных медиагрупп
processed_media_groups = {}

# Словарь для отслеживания обработанных медиагрупп
processed_media_groups = {}

# Обработка медиагрупп
@dp.message_handler(content_types=types.ContentType.ANY)
async def handle_media(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or "Пользователь"  # Получаем ник пользователя или используем "Пользователь"
    
    # Если это часть медиагруппы
    if message.media_group_id:
        media_group_id = message.media_group_id
        
        # Игнорируем уже обработанные медиагруппы
        if media_group_id in processed_media_groups:
            return
        
        # Создаем запись для медиагруппы, если её ещё нет
        if media_group_id not in media_groups:
            media_groups[media_group_id] = {
                "files": [],
                "sender_id": user_id,
                "username": username,  # Сохраняем ник отправителя
                "timestamp": time.time()
            }
        
        # Добавляем файл в медиагруппу
        media_groups[media_group_id]["files"].append(message)
        
        # Ожидаем завершения медиагруппы (например, 5 секунд после последнего файла)
        await asyncio.sleep(5)
        
        # Проверяем, завершена ли медиагруппа
        if media_group_id in media_groups and time.time() - media_groups[media_group_id]["timestamp"] > 5:
            files = media_groups[media_group_id]["files"]
            sender_id = media_groups[media_group_id]["sender_id"]
            sender_username = media_groups[media_group_id]["username"]
            
            # Формируем список медиафайлов
            media = []
            for file in files:
                if file.photo:
                    media.append(types.InputMediaPhoto(file.photo[-1].file_id))
                elif file.document:
                    media.append(types.InputMediaDocument(file.document.file_id))
                elif file.video:
                    media.append(types.InputMediaVideo(file.video.file_id))
            
            # Отправляем медиагруппу каждому администратору
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_media_group(chat_id=admin_id, media=media)
                except Exception as e:
                    logging.error(f"Ошибка при отправке медиагруппы админу {admin_id}: {e}")
            
            # Отправляем информацию о отправителе каждому администратору
            sender_info = f"Медиагруппа от пользователя @{sender_username} (ID: {sender_id})"
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(chat_id=admin_id, text=sender_info)
                except Exception as e:
                    logging.error(f"Ошибка при отправке информации админу {admin_id}: {e}")
            
            # Удаляем медиагруппу из временного словаря
            if media_group_id in media_groups:
                del media_groups[media_group_id]
            
            # Отмечаем медиагруппу как обработанную
            processed_media_groups[media_group_id] = True
    else:
        # Если это отдельный файл, просто пересылаем его каждому администратору
        for admin_id in ADMIN_IDS:
            try:
                await message.forward(chat_id=admin_id)
            except Exception as e:
                logging.error(f"Ошибка при пересылке файла админу {admin_id}: {e}")
        
        # Отправляем информацию о отправителе каждому администратору
        sender_info = f"Файл от пользователя @{message.from_user.username or 'Пользователь'} (ID: {user_id})"
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(chat_id=admin_id, text=sender_info)
            except Exception as e:
                logging.error(f"Ошибка при отправке информации админу {admin_id}: {e}")

# Обновление никнеймов при взаимодействии с ботом
@dp.message_handler()
async def update_user_nickname(message: types.Message):
    user_id = message.from_user.id
    nickname = message.from_user.username  # Берем только username, без "Неизвестный пользователь"
    if nickname:  # Добавляем ник только если он существует
        user_nicknames[user_id] = nickname

async def on_startup(dp):
    # Запускаем обработку очереди сообщений как фоновую задачу
    asyncio.create_task(process_message_queue())

# Запуск бота
if __name__ == '__main__':
    logging.info("Бот запущен")
    load_data()
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
