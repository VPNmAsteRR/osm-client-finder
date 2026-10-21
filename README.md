# Поиск клиентов по OpenStreetMap

**Локальное приложение для поиска компаний по открытым данным.** Выбираешь категорию и город — получаешь список организаций с контактами. Без API-ключей, регистрации и подписок.

<p>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="stdlib" src="https://img.shields.io/badge/зависимости-только%20stdlib-2ea043?style=flat-square">
  <img alt="OSM" src="https://img.shields.io/badge/OpenStreetMap-ODbL-7EBC6F?style=flat-square&logo=openstreetmap&logoColor=white">
  <img alt="Wikidata" src="https://img.shields.io/badge/Wikidata-CC0-006699?style=flat-square&logo=wikidata&logoColor=white">
</p>

## Что умеет

- **18 категорий** — магазины, аптеки, кафе, рестораны, салоны красоты, оптика, электроника, мебель, товары для животных и другие
- **Поиск по названию** — если нужно найти конкретную сеть или бренд
- **Радиус** 2, 5 или 10 км вокруг центра города
- **Обогащение из Wikidata** — описание, сайт, телефоны, email, соцсети, дата основания, картинки
- **Статус Telegram-бота** — есть ли у компании бот в тегах OSM
- **Карточка «Все данные»** — координаты и полный набор тегов OSM
- **Экспорт CSV** — контакты, Wikidata и исходные теги

## Запуск

Нужен только Python 3.9+. Сторонние библиотеки не требуются.

```bash
python3 app.py
```

Приложение слушает `127.0.0.1` на случайном порту и само открывает браузер. Остановка — «Закрыть приложение» в окне или `Ctrl+C`.

**Linux:** можно запустить двойным щелчком по `osm-client-finder.desktop` (в KDE разрешить запуск).

## Как это работает

```
город + категория + радиус
        │
        ├── Nominatim   → координаты центра города
        ├── Overpass    → организации с нужными тегами OSM
        └── Wikidata    → контакты и описание по wikidata=Q…
                │
                └── таблица в браузере → CSV
```

- Между запросами геокодирования есть пауза, центры городов кэшируются
- За один запрос обогащается не более 50 записей Wikidata
- Если Wikidata недоступна, результаты OSM всё равно показываются

## Структура

```
app.py                      HTTP-сервер, поиск, обогащение, экспорт CSV
index.html                  интерфейс приложения
osm-client-finder.desktop   ярлык для Linux
```

## Ограничения

Данные заполняют добровольцы, поэтому у части организаций нет адреса, телефона или связанной записи Wikidata. Публичные Nominatim, Overpass и Wikidata могут ограничивать частоту запросов — приложение кэширует и делает паузы, но злоупотреблять не стоит.

Приложение не обходит сайты компаний: там разные форматы, ограничения и условия использования.

## Источники данных

- © участники OpenStreetMap, лицензия [ODbL](https://www.openstreetmap.org/copyright)
- Wikidata, лицензия [CC0](https://www.wikidata.org/wiki/Wikidata:Licensing)
- [Правила Nominatim](https://operations.osmfoundation.org/policies/nominatim/) · [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API)
