import vk_api
import os
import logging
from dotenv import load_dotenv
from datetime import datetime


load_dotenv()
logger = logging.getLogger(__name__)

class VKClient:
    """Обёртка над VK API для бота-знакомств.

        Создаётся в main() с user-token'ом (VK_TOKEN).
        Методы: get_user_info, build_search_params, search_candidates,
        get_3_candidate_photo, build_profile_url.
        """
    def __init__(self, access_token):
        access_token = access_token or os.getenv('VK_TOKEN')
        if not access_token:
            raise ValueError("VK access token is not provided(env VK_TOKEN is empty).")
        """Получаем api пользователя"""
        self._vk_session = vk_api.VkApi(token=access_token)
        self._api = self._vk_session.get_api()

    @staticmethod
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

    @staticmethod
    def build_profile_url(person: dict) -> str:
        """Формируем ссылку на профиль пользователя."""
        screen_name = person.get('screen_name')
        if screen_name:
            return f"https://vk.com/{screen_name}"
        user_id = person.get('id')
        if user_id:
            return f"https://vk.com/id{user_id}"
        logger.warning("Cannot build URL: no screen_name or id in %r", person)
        return ""

    def get_user_info(self, user_id):
        """Получаем информацию о пользователе.

        Возвращает dict с полями: id, city_id, sex, age.
        Возвращает None, если данные недоступны (скрытый профиль,
        ошибка API и т.д.).
        """
        try:
            users = self._api.users.get(user_ids=user_id, fields='city,sex,bdate')
        except vk_api.exceptions.ApiError as e:
            logger.error("get_user_info failed for user %s: %s", user_id, e)
            return None
        if not users:
            logger.warning("No user found with id %s", user_id)
            return None
        user = users[0]
        city = user.get('city') or {}
        user_info = {
            'id': user.get('id'),
            'city_id': city.get('id'),
            'sex': user.get('sex'),
            'age':  self.bdate_to_age(user.get('bdate'))
        }
        logger.info("get_user_info for user %s: %r", user_id, user_info)
        return user_info

    def build_search_params(self, user_id):
        """Получаем параметры поиска.

        Возвращает dict с параметрами для api.users.search или None,
        если данные пользователя недостаточны для поиска.
        """
        user_info = self.get_user_info(user_id)
        if user_info is None:
            return None

        if user_info.get('age') is None or user_info.get('city_id') is None or user_info.get('sex') == 0:
            return None

        if user_info.get('sex') == 2:
            sex = 1
        elif user_info.get('sex') == 1:
            sex = 2
        else:
            logger.warning("Unknown sex value: %r", user_info.get('sex'))
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


    def search_candidates(self, user_id):
        """Получаем список кандидатов.

        Возвращает список dicts с информацией о кандидатах или пустой список.
        """
        search_params = self.build_search_params(user_id)
        if search_params is None:
            logging.warning("[search] build_search_params -> None, user=%s", user_id)
            return []
        logging.info("[search] params: %r", search_params)

        try:
            result = self._api.users.search(**search_params)
        except vk_api.exceptions.ApiError as e:
            logging.error("[search] API error for user %s: %s", user_id, e)
            return []
        items = result.get('items', [])
        logging.info("[search] VK returned %d items; response count=%r",
                    len(items), result.get('count'))

        if items:
            logging.info("[search] sample bdate values: %r",
                     [it.get('bdate') for it in items[:5]])

        candidates_info = []
        for candidate in result.get('items', []):
            # age = self.bdate_to_age(candidate.get('bdate'))
            # if age is None:
            #     continue
            person_info = {
                'candidate_id': candidate.get('id'),
                'name': candidate.get('first_name'),
                'surname': candidate.get('last_name'),
                'link': self.build_profile_url(candidate),
            }
            candidates_info.append(person_info)
        logger.info("[search] kept %d candidates", len(candidates_info))
        return candidates_info

    def get_3_candidate_photo(self, candidate_id):
        """Получаем 3 самых популярных фото кандидата.

        Возвращает список attachment-строк или пустой список при ошибке.
        """
        try:
            response = self._api.photos.get(
                owner_id=candidate_id,
                album_id='profile',
                rev=0,
                extended=1,
            )
        except vk_api.exceptions.ApiError as e:
            if getattr(e, 'code', None) == 30:
                logger.info("Candidate %s is private — skip photos", candidate_id)
            else:
                logger.error("photos.get failed for %s: %s", candidate_id, e)
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


