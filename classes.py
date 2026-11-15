import vk_api
import os
from dotenv import load_dotenv
from datetime import datetime
from db import VKUser, Candidates, Photo, Favorites, BlackList, session
import sqlalchemy
from sqlalchemy import select

load_dotenv()
access_token = os.getenv('VK_TOKEN')
# user_id = os.getenv('ID')
app_id = os.getenv('APP_ID')
token = os.getenv('TOKEN')


class ApiVK:

    def __init__(self, access_token):
        self.access_token = access_token
        """Получаем api пользователя"""
        user = vk_api.VkApi(token=access_token)
        self.api = user.get_api()

    def get_city_id(self, city):
        """Получаем ID города"""
        cities = self.api.database.getCities(
            country_id=1,      # 1 — Россия
            q=city,            # Поиск по названию
            count=1            # Нам нужен только первый результат
        )
        # Извлекаем ID
        city_id = cities['items'][0]['id']
        return city_id

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
        """Получаем информацию о пользователе"""
        user = self.api.users.get(user_ids=user_id, fields='city,sex,bdate')[0]
        user_info = {'id': user.get('id'),
                     'city': user.get('city').get('title'),
                     'city_id': user.get('city').get('id'),
                     'sex': user.get('sex'),
                     'age': self.bdate_to_age(user.get('bdate'))}

        return user_info

    def build_search_params(self, user_id):
        """Получаем параметры поиска"""
        user_info = self.get_user_info(user_id)
        if user_info.get('age') is None or user_info.get('city_id') is None or user_info.get('sex') == 0:
            return None
        if user_info.get('sex') == 2:
            sex = 1
        elif user_info.get('sex') == 1:
            sex = 2
        city_id = user_info.get('city_id')
        age_from = user_info.get('age') - 5
        age_to = user_info.get('age') + 5
        return {'sex': sex, 'city': city_id, 'age_from': age_from, 'age_to': age_to, 'has_photo': 1, 'count': 1000, 'fields': 'has_photo,city,sex,bdate'}

    def build_profile_url(self, person: dict) -> str:
        screen_name = person.get('screen_name')
        if screen_name:
            return f"https://vk.com/{screen_name}"
        return f"https://vk.com/id{person['id']}"

    def search_candidates(self, user_id):
        """Получаем список кандидатов"""
        candidates = self.api.users.search(**self.build_search_params(user_id))
        candidates_info = []
        for candidate in candidates['items']:
            if candidate.get('sex') == 2:
                gender = 'мужской'
            elif candidate.get('sex') == 1:
                gender = 'женский'
            else:
                gender = ''
            age = self.bdate_to_age(candidate.get('bdate'))
            if age is None:
                continue
            person_info = {
                'candidate_id': candidate.get('id'),
                'name': candidate.get('first_name'),
                'surname': candidate.get('last_name'),
                'link': self.build_profile_url(candidate)
            }
            candidates_info.append(person_info)
        return candidates_info

    def get_3_candidate_photo(self, candidate_id):
        try:
            response = self.api.photos.get(owner_id=candidate_id, album_id='profile', rev=0, extended=1)
            all_photos = response.get('items')
        except vk_api.exceptions.ApiError:
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

    def __init__(self, access_token):
        ApiVK.__init__(self, access_token)

    def insert_vk_user(self, user_id): #вставка в таблицу vk_user
        """Заполнение таблицы vk_user"""
        user_info = self.get_user_info(user_id)
        age = user_info.get('age')
        sex = user_info.get('sex')
        city_id = user_info.get('city_id')
        if not age or not sex or not city_id:
            return None
        vk_user = VKUser(id=user_id, age=age, sex=sex, city_id=city_id)
        merged = session.merge(vk_user)
        session.commit()
        return merged

    def insert_candidates(self, user_id): #вставка в таблицу candidates
        """Заполнение таблицы candidates"""
        # session = Session()
        try:
            candidates_info = self.search_candidates(user_id) #получаем список кандидатов
            if not candidates_info:
                return []
            # Уже сохранённые vk_id этого владельца
            existing = set(session.execute(select(Candidates.vk_id).where(Candidates.owner_id == user_id)).scalars())
            new_candidates = []
            for candidate in candidates_info:
                if candidate.get('candidate_id') in existing:
                    continue
                # Добавляем в таблицу Candidates
                new_candidates.append(Candidates(vk_id=candidate.get('candidate_id'),
                                                 owner_id=user_id,
                                                 name=candidate.get('name'),
                                                 surname=candidate.get('surname'),
                                                 link=candidate.get('link')))
            if new_candidates:
                session.add_all(new_candidates)
                session.commit()
            return session.execute(
                select(Candidates)
                .where(Candidates.owner_id == user_id)
                .order_by(Candidates.id)
            ).scalars().all()
        except Exception:
            session.rollback()
            raise

    def insert_photos(self, user_id): #вставка в таблицу photos
        """Заполнение таблицы photos"""
        # session = Session()
        try:
            candidates = session.execute(select(Candidates).where(Candidates.owner_id == user_id)).scalars().all()
            for cand in candidates:
                already = session.execute(select(sq.func.count(Photo.id)).where(Photo.candidate_id == cand.id)).scalar_one()
                if already:
                    continue

                for att in self.get_3_candidate_photo(api, cand.vk_id):
                    session.add(Photo(candidate_id=cand.id, attachment=att))
            session.commit()
        except Exception:
            session.rollback()
            raise

    def show_next_candidate(self, vk_user_id, vk, session):
        vk_user = session.get(VKUser, vk_user_id)
        if vk_user is None:
            return None
        blacklisted_ids = (select(BlackList.candidate_id).where(BlackList.vk_user_id == vk_user_id))
        candidate = (session.query(Candidates).filter(Candidates.owner_id == vk_user_id,
                                                      Candidates.id > vk_user.last_shown_id,
                                                      ~Candidates.id.in_(blacklisted_ids))
                     .order_by(Candidates.id)
                     .first())

        if candidate is None:
            return False
        vk_user.last_shown_id = candidate.id
        session.commit()

        # формируем сообщение
        text = (
            f"{candidate.name} {candidate.surname}\n"
            f"{candidate.link}"
        )
        attachment = ",".join(p.attachment for p in candidate.photos)  # "photo...,photo...,photo..."

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

    def add_to_favorite(self, user_id, session):
        favorite_id = session.execute(select(VKUser.last_shown_id).where(VKUser.id == user_id)).scalar_one()
        if not favorite_id:
            return "Нет активного кандидата, начните поиск"
        exiting = session.get(Favorites, (user_id, favorite_id))
        if not exiting:
            favorite = Favorites(vk_user_id=user_id, candidate_id=favorite_id)
            session.add(favorite)
        session.commit()
        return "Кандидат добавлен в избранное"

    def add_to_black_list(self, user_id, session):
        ban_candidate_id = session.execute(select(VKUser.last_shown_id).where(VKUser.id == user_id)).scalar_one()
        if not ban_candidate_id:
            return "Нет активного кандидата, начните поиск"
        exiting = session.get(BlackList, (user_id, ban_candidate_id))
        if not exiting:
            ban_candidate = BlackList(vk_user_id=user_id, candidate_id=ban_candidate_id)
            session.add(ban_candidate)
        session.commit()
        return "Кандидат добавлен в черный список"

    def show_favorite_list(self, user_id, session):
        candidates = session.execute(
            select(Candidates)
            .join(Favorites, Favorites.candidate_id == Candidates.id)
            .where(Favorites.vk_user_id == user_id)
            .options(selectinload(Candidates.photos))    # фото сразу, без N+1
            .order_by(Candidates.id)
        ).scalars().all()

        if not candidates:
            return "Нет избранных кандидатов"

        return candidates
