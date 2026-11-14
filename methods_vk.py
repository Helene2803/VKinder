import vk_api
import os
import logging
from dotenv import load_dotenv
from datetime import datetime


load_dotenv()
access_token = os.getenv('VK_TOKEN')
app_id = os.getenv('APP_ID')
token = os.getenv('TOKEN')


def api_user(access_token):
    """Получаем api пользователя"""
    user=vk_api.VkApi(token=access_token)
    api = user.get_api()
    return api

def bdate_to_age(bdate: str) -> int | None:
    """Возвращает возраст числом или None, если год скрыт."""
    if not bdate:
        return None

    parts = bdate.split('.')
    if len(parts) != 3:          # "DD.MM" — год скрыт, возраст неизвестен
        return None

    day, month, year = map(int, parts)
    today = datetime.today()
    age = today.year - year - ((today.month, today.day) < (month, day))
    return age

def get_user_info(api, user_id):
    """Получаем информацию о пользователе.

    Возвращает dict с полями: id, city_id, sex, age.
    Возвращает None, если данные недоступны (скрытый профиль,
    ошибка API и т.д.).
    """
    try:
        users = api.users.get(user_ids=user_id, fields='city,sex,bdate')
    except vk_api.exceptions.ApiError as e:
        print(f"[get_user_info] API error for user {user_id}: {e}")
        return None

    if not users:
        print(f"[get_user_info] No user found with id {user_id}")
        return None

    user = users[0]

    city = user.get('city')
    city_id = city.get('id') if city else None

    bdate = user.get('bdate')
    age = bdate_to_age(bdate) if bdate else None

    sex = user.get('sex')

    return {
        'id': user.get('id'),
        'city_id': city_id,
        'sex': sex,
        'age': age,
    }

# print(get_user_info(api,user_id))

def build_search_params(api, user_id):
    """Получаем параметры поиска.

    Возвращает dict с параметрами для api.users.search или None,
    если данные пользователя недостаточны для поиска.
    """
    user_info = get_user_info(api, user_id)
    if user_info is None:
        print(f"[build_search_params] Cannot build params: get_user_info returned None for {user_id}")
        return None

    if user_info.get('age') is None or user_info.get('city_id') is None or user_info.get('sex') == 0:
        return None

    if user_info.get('sex') == 2:
        sex = 1
    elif user_info.get('sex') == 1:
        sex = 2
    else:
        print(f"[build_search_params] Unknown sex value: {user_info.get('sex')}")
        return None

    city_id = user_info.get('city_id')
    age_from = user_info.get('age') - 5
    age_to = user_info.get('age') + 5

    return {
        'sex': sex,
        'city': city_id,
        'age_from': age_from,
        'age_to': age_to,
        'has_photo': 1,
        'count': 1000,
        'fields': 'has_photo,city,sex,bdate',
    }

def build_profile_url(person: dict) -> str:
    """Формируем ссылку на профиль пользователя."""
    screen_name = person.get('screen_name')
    if screen_name:
        return f"https://vk.com/{screen_name}"
    user_id = person.get('id')
    if user_id:
        return f"https://vk.com/id{user_id}"
    print(f"[build_profile_url] Cannot build URL: no screen_name or id in {person}")
    return ""

def search_candidates(api, user_id):
    """Получаем список кандидатов.

    Возвращает список dicts с информацией о кандидатах или пустой список.
    """
    search_params = build_search_params(api, user_id)
    if search_params is None:
        logging.warning("[search] build_search_params -> None, user=%s", user_id)
        print(f"[search_candidates] Cannot search: build_search_params returned None for {user_id}")
        return []
    logging.info("[search] params: %r", search_params)

    try:
        result = api.users.search(**search_params)
    except vk_api.exceptions.ApiError as e:
        logging.error("[search] API error for user %s: %s", user_id, e)
        print(f"[search_candidates] API error for user {user_id}: {e}")
        return []
    items = result.get('items', [])
    logging.info("[search] VK returned %d items; response count=%r",
                 len(items), result.get('count'))

    if items:
        logging.info("[search] sample bdate values: %r",
                     [it.get('bdate') for it in items[:5]])

    candidates_info = []
    for candidate in result.get('items', []):
        age = bdate_to_age(candidate.get('bdate'))
        if age is None:
            continue

        person_info = {
            'candidate_id': candidate.get('id'),
            'name': candidate.get('first_name'),
            'surname': candidate.get('last_name'),
            'link': build_profile_url(candidate),
        }
        candidates_info.append(person_info)

    return candidates_info

def get_3_candidate_photo(api, candidate_id):
    """Получаем 3 самых популярных фото кандидата.

    Возвращает список attachment-строк или пустой список при ошибке.
    """
    try:
        response = api.photos.get(
            owner_id=candidate_id,
            album_id='profile',
            rev=0,
            extended=1,
        )
    except vk_api.exceptions.ApiError as e:
        print(f"[get_3_candidate_photo] API error for candidate {candidate_id}: {e}")
        return []

    all_photos = response.get('items')
    if not all_photos:
        return []

    top_3_photos = sorted(all_photos, key=lambda x: x['likes']['count'], reverse=True)[:3]
    result = []
    for photo in top_3_photos:
        att = f'photo{photo["owner_id"]}_{photo["id"]}'
        if photo.get('access_key'):
            att += f"_{photo['access_key']}"
        result.append(att)
    return result
