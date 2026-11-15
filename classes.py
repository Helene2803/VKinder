import vk_api
import os
import logging
from dotenv import load_dotenv
from datetime import datetime
from db import VKUser, Candidates, Photo, Favorites, BlackList, session
import sqlalchemy as sq
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from random import randrange

load_dotenv()
access_token = os.getenv('VK_TOKEN')
app_id = os.getenv('APP_ID')
token = os.getenv('TOKEN')


class ApiVK:

    def __init__(self, access_token):
        self.access_token = access_token
        """Получаем api пользователя"""
        user = vk_api.VkApi(token=access_token)
        self.api = user.get_api()

    def bdate_to_age(self, bdate: str) -> int | None:
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

    def get_user_info(self, user_id):
        """Получаем информацию о пользователе.

        Возвращает dict с полями: id, city_id, sex, age.
        Возвращает None, если данные недоступны (скрытый профиль,
        ошибка API и т.д.).
        """
        try:
            users = self.api.users.get(user_ids=user_id, fields='city, sex, bdate')
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
        age = self.bdate_to_age(bdate) if bdate else None

        sex = user.get('sex')

        return {
            'id': user.get('id'),
            'city_id': city_id,
            'sex': sex,
            'age': age,
        }

    def build_search_params(self, user_id):
        """Получаем параметры поиска.

        Возвращает dict с параметрами для api.users.search или None,
        если данные пользователя недостаточны для поиска.
        """
        user_info = self.get_user_info(user_id)
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
            'fields': 'has_photo, city, sex, bdate',
        }

    def build_profile_url(self, person: dict) -> str:
        """Формируем ссылку на профиль пользователя."""
        screen_name = person.get('screen_name')
        if screen_name:
            return f"https://vk.com/{screen_name}"
        user_id = person.get('id')
        if user_id:
            return f"https://vk.com/id{user_id}"
        print(f"[build_profile_url] Cannot build URL: no screen_name or id in {person}")
        return ""

    def search_candidates(self, user_id):
        """Получаем список кандидатов.

        Возвращает список dicts с информацией о кандидатах или пустой список.
        """
        search_params = self.build_search_params(user_id)
        if search_params is None:
            logging.warning("[search] build_search_params -> None, user=%s", user_id)
            print(f"[search_candidates] Cannot search: build_search_params returned None for {user_id}")
            return []
        logging.info("[search] params: %r", search_params)

        try:
            result = self.api.users.search(**search_params)
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
            age = self.bdate_to_age(candidate.get('bdate'))
            if age is None:
                continue

            person_info = {
                'candidate_id': candidate.get('id'),
                'name': candidate.get('first_name'),
                'surname': candidate.get('last_name'),
                'link': self.build_profile_url(candidate),
            }
            candidates_info.append(person_info)

        return candidates_info

    def get_3_candidate_photo(self, candidate_id):
        """Получаем 3 самых популярных фото кандидата.

        Возвращает список attachment-строк или пустой список при ошибке.
        """
        try:
            response = self.api.photos.get(
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


class DB(ApiVK):

    def __init__(self, access_token, session):
        ApiVK.__init__(self, access_token)
        self.session = session

    def insert_vk_user(self, user_id):
        """Создаёт или обновляет профиль пользователя в таблице vk_user.

        Получает данные из VK (возраст, пол, город) через get_user_info.
        Возвращает объект VKUser или None, если данные неполны.
        """
        user_info = self.get_user_info(user_id)
        age = user_info.get('age')
        sex = user_info.get('sex')
        city_id = user_info.get('city_id')
        if not age or not sex or not city_id:
            return None
        vk_user = VKUser(id=user_id, age=age, sex=sex, city_id=city_id)
        merged = self.session.merge(vk_user)
        self.session.commit()
        return merged

    def insert_candidates(self, user_id):
        """Находит кандидатов через VK API и сохраняет в таблицу candidates.

        Проверяет дубликаты по vk_id для текущего пользователя.
        Возвращает список всех кандидатов пользователя или пустой список.
        """
        # session = Session()
        try:
            candidates_info = self.search_candidates(user_id)
            if not candidates_info:
                return []
            existing = set(
                self.session.execute(
                    select(Candidates.vk_id).where(Candidates.owner_id == user_id)
                ).scalars()
            )
            new_candidates = []
            for candidate in candidates_info or []:
                if candidate.get('candidate_id') in existing:
                    continue
                new_candidates.append(Candidates(
                    vk_id=candidate.get('candidate_id'),
                    owner_id=user_id,
                    name=candidate.get('name'),
                    surname=candidate.get('surname'),
                    link=candidate.get('link'),
                ))
            if new_candidates:
                self.session.add_all(new_candidates)
                self.session.commit()
            return self.session.execute(
                select(Candidates)
                .where(Candidates.owner_id == user_id)
                .order_by(Candidates.id)
            ).scalars().all()
        except Exception:
            self.session.rollback()
            raise

    def insert_photos(self, user_id):
        """Сохраняет до 3 популярных фото для каждого кандидата пользователя.

        Пропускает кандидатов, у которых фото уже сохранены.
        """
        # session = Session()
        try:
            candidates = self.session.execute(
                select(Candidates).where(Candidates.owner_id == user_id)
            ).scalars().all()
            for cand in candidates:
                already = self.session.execute(
                    select(sq.func.count(Photo.id)).where(Photo.candidate_id == cand.id)
                ).scalar_one()
                if already:
                    continue
                for att in self.get_3_candidate_photo(cand.vk_id):
                    self.session.add(Photo(candidate_id=cand.id, attachment=att))
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def show_next_candidate(self, vk_user_id, vk):
        """Показывает следующего кандидата пользователю.

        Выбирает кандидата с id > last_shown_id, исключая из чёрного списка.
        Формирует сообщение с клавиатурой и отправляет через VK API.
        Возвращает True при успехе, False если кандидатов больше нет.
        """
        vk_user = self.session.get(VKUser, vk_user_id)
        if vk_user is None:
            return None
        blacklisted_ids = (
            select(BlackList.candidate_id).where(BlackList.vk_user_id == vk_user_id)
        )
        candidate = (
            self.session.query(Candidates)
            .filter(
                Candidates.owner_id == vk_user_id,
                Candidates.id > vk_user.last_shown_id,
                ~Candidates.id.in_(blacklisted_ids),
                )
            .order_by(Candidates.id)
            .first()
        )

        if candidate is None:
            return False
        vk_user.last_shown_id = candidate.id
        self.session.commit()

        text = (
            f"{candidate.name} {candidate.surname}\n"
            f"{candidate.link}"
        )
        attachment = ",".join(p.attachment for p in candidate.photos)

        keyboard = VkKeyboard(one_time=False)
        keyboard.add_button("Далее", color=VkKeyboardColor.PRIMARY)
        keyboard.add_button("В избранное", color=VkKeyboardColor.POSITIVE)
        keyboard.add_button("В ЧС", color=VkKeyboardColor.NEGATIVE)

        params = {
            'user_id': vk_user_id,
            'message': text,
            'keyboard': keyboard.get_keyboard(),
            'random_id': randrange(10**7),
        }
        if attachment:
            params['attachment'] = attachment
        try:
            vk.method('messages.send', params)
        except Exception as e:
            print(f"[SNC] send failed for candidate {candidate.id}: {e}")

        return True

    def add_to_favorite(self, user_id):
        """Добавляет текущего кандидата в избранное.

        Возвращает текстовое сообщение о результате (успех или ошибка).
        """
        favorite_id = self.session.execute(
            select(VKUser.last_shown_id).where(VKUser.id == user_id)
        ).scalar_one()
        if not favorite_id:
            return "Нет активного кандидата, начните поиск"
        exiting = self.session.get(Favorites, (user_id, favorite_id))
        if not exiting:
            favorite = Favorites(vk_user_id=user_id, candidate_id=favorite_id)
            self.session.add(favorite)
        self.session.commit()
        return "Кандидат добавлен в избранное"

    def add_to_black_list(self, user_id):
        """Добавляет текущего кандидата в чёрный список.

        Возвращает текстовое сообщение о результате (успех или ошибка).
        """
        ban_candidate_id = self.session.execute(
            select(VKUser.last_shown_id).where(VKUser.id == user_id)
        ).scalar_one()
        if not ban_candidate_id:
            return "Нет активного кандидата, начните поиск"
        exiting = self.session.get(BlackList, (user_id, ban_candidate_id))
        if not exiting:
            ban_candidate = BlackList(vk_user_id=user_id, candidate_id=ban_candidate_id)
            self.session.add(ban_candidate)
        self.session.commit()
        return "Кандидат добавлен в черный список"

    def show_favorite_list(self, user_id):
        """Возвращает список избранных кандидатов с их фото.

        Возвращает список объектов Candidates или сообщение "Нет избранных кандидатов".
        """
        candidates = self.session.execute(
            select(Candidates)
            .join(Favorites, Favorites.candidate_id == Candidates.id)
            .where(Favorites.vk_user_id == user_id)
            .options(selectinload(Candidates.photos))
            .order_by(Candidates.id)
        ).scalars().all()

        if not candidates:
            return "Нет избранных кандидатов"

        return candidates

