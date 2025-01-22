import logging
import asyncio
import requests
import html
import os
import numpy as np
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, InputFile
from aiogram.client.default import DefaultBotProperties
from deep_translator import GoogleTranslator

FOOD_API_URL = "https://world.openfoodfacts.org/cgi/search.pl"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

users = {}

LOW_CALORIE_FOODS = [
    {"name": "Огурец", "calories": 15},
    {"name": "Помидор", "calories": 18},
    {"name": "Куриная грудка", "calories": 165},
    {"name": "Творог обезжиренный", "calories": 70},
    {"name": "Яблоко", "calories": 52}
]

WORKOUTS = {
    "low": ["Йога (30 мин) - 150 ккал", "Пешая прогулка (45 мин) - 200 ккал"],
    "medium": ["Велосипед (30 мин) - 300 ккал", "Плавание (30 мин) - 250 ккал"],
    "high": ["Бег (30 мин) - 400 ккал", "Кроссфит (30 мин) - 500 ккал"]
}

async def get_weather(city: str) -> float:
    """Получение температуры через OpenWeatherMap API"""
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric"
        response = requests.get(url).json()
        return response['main']['temp']
    except Exception as e:
        logging.error(f"Ошибка погодного API: {e}")
        return 20.0 
        
def calculate_water(profile: dict) -> int:
    """Расчет дневной нормы воды"""
    base = profile["weight"] * 30
    activity = (profile["activity"] // 30) * 500
    weather = 500 if profile.get("temperature", 20) > 25 else 0
    return base + activity + weather

def calculate_calories(profile: dict) -> int:
    """Расчет дневной нормы калорий"""
    weight = profile["weight"]
    height = profile["height"]
    age = profile["age"]
    
    if profile.get("gender") == "male":
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161
    
    activity_factor = 1.2 + (profile["activity"] / 60) * 0.1
    return int(bmr * activity_factor)

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    await message.answer(
        "👋 Привет! Я FitBalanceBot 🤖\n"
        "Я помогу тебе отслеживать:\n"
        "💧 Потребление воды\n"
        "🍎 Калорийность питания\n"
        "🏋️ Активность и тренировки\n\n"
        "Начни с настройки профиля: /set_profile"
    )

@dp.message(Command("set_profile"))
async def cmd_set_profile(message: Message):
    """Настройка профиля пользователя"""
    user_id = message.from_user.id
    users[user_id] = {
        "step": "weight",
        "history": {"dates": [], "water": [], "calories": []}
    }
    await message.answer("📏 Введите ваш вес в килограммах:")

@dp.message(Command("faq"))
async def cmd_faq(message: Message):
    """Справка по командам"""
    faq_text = (
        "📚 <b>Доступные команды:</b>\n\n"
        "💧 /log_water [объем] - Записать потребление воды (в мл)\n"
        "🍎 /log_food [продукт] - Записать съеденный продукт\n"
        "🏋️ /log_workout [тип] [минуты] - Записать тренировку\n"
        "📊 /check_progress - Текущий прогресс\n"
        "💡 /recommend - Персональные рекомендации\n"
        "⚙️ /set_profile - Настройка профиля\n"
        "❓ /faq - Повторный показ справки"
    )
    await message.answer(faq_text, parse_mode=ParseMode.HTML)

@dp.message(Command("log_water"))
async def cmd_log_water(message: Message):
    """Логирование воды"""
    user_id = message.from_user.id
    if user_id not in users:
        return await message.answer("⚠ Сначала настройте профиль: /set_profile")
    
    try:
        amount = int(message.text.split()[1])
        if amount <= 0:
            raise ValueError
        
        users[user_id]["logged_water"] += amount
        remaining = users[user_id]["water_goal"] - users[user_id]["logged_water"]
        
        users[user_id]["history"]["dates"].append(datetime.now().date())
        users[user_id]["history"]["water"].append(amount)
        
        await message.answer(
            f"💧 +{amount} мл воды!\n"
            f"📊 Прогресс: {users[user_id]['logged_water']}/{users[user_id]['water_goal']} мл\n"
            f"⏳ Осталось: {remaining} мл"
        )
    except (IndexError, ValueError):
        await message.answer(
            "❌ Неверный формат!\n"
            "Пример использования: /log_water 500\n"
            "Введите положительное число"
        )

@dp.message(Command("log_food"))
async def cmd_log_food(message: Message):
    """Логирование питания"""
    user_id = message.from_user.id
    if user_id not in users:
        return await message.answer("⚠ Сначала настройте профиль: /set_profile")
    
    try:
        product_ru = ' '.join(message.text.split()[1:])
        if not product_ru:
            raise ValueError("Не указан продукт")
        
        product_en = GoogleTranslator(source='ru', target='en').translate(product_ru)
        
        params = {
            'search_terms': product_en,
            'json': 1,
            'page_size': 1
        }
        response = requests.get(FOOD_API_URL, params=params)
        data = response.json()
        
        if not data.get('products'):
            raise ValueError("Продукт не найден")
        
        product = data['products'][0]
        calories = product.get('nutriments', {}).get('energy-kcal_100g', 0)
        
        if not calories:
            raise ValueError("Нет данных о калорийности")
        
        users[user_id]["_food"] = calories
        product_name = product.get('product_name_ru') or product_ru
        
        await message.answer(
            f"🍎 {product_name.capitalize()}\n"
            f"🔢 Калорийность: {calories} ккал/100г\n"
            "📏 Сколько грамм вы съели?"
        )
        
    except Exception as e:
        await message.answer(
            f"❌ Ошибка: {str(e)}\n"
            "Пример использования: /log_food банан\n"
            "Попробуйте уточнить название продукта"
        )

@dp.message(Command("log_workout"))
async def cmd_log_workout(message: Message):
    """Логирование тренировок"""
    user_id = message.from_user.id
    if user_id not in users:
        return await message.answer("⚠ Сначала настройте профиль: /set_profile")
    
    try:
        args = message.text.split()[1:]
        if len(args) < 2:
            raise ValueError
        
        workout_type = ' '.join(args[:-1]).lower()
        duration = int(args[-1])
        
        calories_burned = duration * 8
        water_bonus = (duration // 30) * 200
        
        users[user_id]["burned_calories"] += calories_burned
        users[user_id]["water_goal"] += water_bonus
        
        users[user_id]["history"]["dates"].append(datetime.now().date())
        users[user_id]["history"]["calories"].append(calories_burned)
        
        await message.answer(
            f"🏋️ {workout_type.capitalize()} {duration} минут\n"
            f"🔥 Сожжено: {calories_burned} ккал\n"
            f"💦 Рекомендуется воды: +{water_bonus} мл\n"
            f"📈 Новая норма воды: {users[user_id]['water_goal']} мл"
        )
    except (ValueError, IndexError):
        await message.answer(
            "❌ Неверный формат!\n"
            "Пример использования: /log_workout бег 30\n"
            "Доступные типы тренировок: бег, плавание, велосипед и др."
        )

@dp.message(Command("check_progress"))
async def cmd_check_progress(message: Message):
    """Проверка прогресса"""
    user_id = message.from_user.id
    if user_id not in users:
        return await message.answer("⚠ Сначала настройте профиль: /set_profile")
    
    profile = users[user_id]
    water_remaining = profile["water_goal"] - profile["logged_water"]
    calories_balance = profile["calorie_goal"] - profile["logged_calories"] + profile["burned_calories"]
    
    progress_text = (
        f"📊 <b>Ваш прогресс за {datetime.now().strftime('%d.%m.%Y')}</b>\n\n"
        f"💧 Вода:\n"
        f"• Выпито: {profile['logged_water']} мл из {profile['water_goal']} мл\n"
        f"• Осталось: {water_remaining} мл\n\n"
        f"🍏 Калории:\n"
        f"• Потреблено: {profile['logged_calories']:.1f} ккал\n"
        f"• Сожжено: {profile['burned_calories']} ккал\n"
        f"• Баланс: {calories_balance:.1f}/{profile['calorie_goal']} ккал"
    )
    await message.answer(progress_text, parse_mode=ParseMode.HTML)


@dp.message(Command("recommend"))
async def cmd_recommend(message: Message):
    """Персональные рекомендации"""
    user_id = message.from_user.id
    if user_id not in users:
        return await message.answer("⚠ Сначала настройте профиль: /set_profile")
    
    profile = users[user_id]
    balance = profile['calorie_goal'] - profile['logged_calories']
    
    food = np.random.choice(LOW_CALORIE_FOODS)
    
    if balance > 500:
        workout_type = "low"
    elif balance > 300:
        workout_type = "medium"
    else:
        workout_type = "high"
    
    workout = np.random.choice(WORKOUTS[workout_type])
    
    await message.answer(
        f"💡 <b>Персональные рекомендации</b>\n\n"
        f"🍏 Низкокалорийный продукт:\n"
        f"{food['name']} ({food['calories']} ккал/100г)\n\n"
        f"🏋️ Рекомендуемая тренировка:\n"
        f"{workout}\n\n"
        f"⚖️ Текущий баланс: {balance:.1f} ккал",
        parse_mode=ParseMode.HTML
    )

@dp.message(lambda msg: users.get(msg.from_user.id, {}).get('step') == 'weight')
async def process_weight(message: Message):
    user_id = message.from_user.id
    try:
        weight = int(message.text)
        if weight <= 0:
            raise ValueError
        users[user_id]["weight"] = weight
        users[user_id]["step"] = "height"
        await message.answer("📏 Введите ваш рост в сантиметрах:")
    except ValueError:
        await message.answer("❌ Введите корректный вес (положительное число)")

@dp.message(lambda msg: users.get(msg.from_user.id, {}).get('step') == 'height')
async def process_height(message: Message):
    user_id = message.from_user.id
    try:
        height = int(message.text)
        if height <= 0:
            raise ValueError
        users[user_id]["height"] = height
        users[user_id]["step"] = "age"
        await message.answer("🎂 Введите ваш возраст:")
    except ValueError:
        await message.answer("❌ Введите корректный рост (положительное число)")

@dp.message(lambda msg: users.get(msg.from_user.id, {}).get('step') == 'age')
async def process_age(message: Message):
    user_id = message.from_user.id
    try:
        age = int(message.text)
        if age <= 0:
            raise ValueError
        users[user_id]["age"] = age
        users[user_id]["step"] = "activity"
        await message.answer("🏃 Введите минуты ежедневной активности:")
    except ValueError:
        await message.answer("❌ Введите корректный возраст (положительное число)")

@dp.message(lambda msg: users.get(msg.from_user.id, {}).get('step') == 'activity')
async def process_activity(message: Message):
    user_id = message.from_user.id
    try:
        activity = int(message.text)
        if activity < 0:
            raise ValueError
        users[user_id]["activity"] = activity
        users[user_id]["step"] = "city"
        await message.answer("🌍 Введите ваш город для учета погоды:")
    except ValueError:
        await message.answer("❌ Введите корректное количество минут")

@dp.message(lambda msg: users.get(msg.from_user.id, {}).get('step') == 'city')
async def process_city(message: Message):
    user_id = message.from_user.id
    try:
        city = message.text.strip()
        if not city:
            raise ValueError
        
        users[user_id]["city"] = city
        users[user_id]["temperature"] = await get_weather(city)
        
        users[user_id]["water_goal"] = calculate_water(users[user_id])
        users[user_id]["calorie_goal"] = calculate_calories(users[user_id])
        
        users[user_id].update({
            "logged_water": 0,
            "logged_calories": 0.0,
            "burned_calories": 0
        })
        
        del users[user_id]["step"]
        
        await message.answer(
            f"✅ <b>Профиль сохранен!</b>\n\n"
            f"💧 Дневная норма воды: {users[user_id]['water_goal']} мл\n"
            f"🍏 Дневная норма калорий: {users[user_id]['calorie_goal']} ккал\n\n"
            "Используйте /faq для списка команд",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.message(lambda msg: users.get(msg.from_user.id, {}).get('_food'))
async def process_food_weight(message: Message):
    user_id = message.from_user.id
    try:
        grams = int(message.text)
        if grams <= 0:
            raise ValueError
        
        calories = (users[user_id]["_food"] * grams) / 100
        users[user_id]["logged_calories"] += calories
        
        users[user_id]["history"]["dates"].append(datetime.now().date())
        users[user_id]["history"]["calories"].append(calories)
        
        del users[user_id]["_food"]
        
        await message.answer(
            f"🍽 Съедено: {grams}г\n"
            f"🔥 Записано: {calories:.1f} ккал\n"
            f"📊 Всего: {users[user_id]['logged_calories']:.1f}/"
            f"{users[user_id]['calorie_goal']} ккал"
        )
    except ValueError:
        await message.answer("❌ Введите корректное количество грамм")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
