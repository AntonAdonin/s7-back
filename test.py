from SPARQLWrapper import SPARQLWrapper, JSON


def get_entities_data(q_ids, lang="ru"):
    """
    Принимает список Q-идентификаторов и возвращает данные сущностей, включая:
      - Название (itemLabel)
      - Описание (description)
      - Изображение (P18)
      - Тип объекта (instance of, P31)
      - Географические координаты (P625)
      - Административное деление (P131)
      - Официальный сайт (P856)
      - Дата основания (P571)

    :param q_ids: список идентификаторов (например, ["Q42", "Q5", "Q64"])
    :param lang: язык для меток и описаний (по умолчанию "ru")
    :return: список словарей с данными сущностей
    """
    sparql = SPARQLWrapper("https://query.wikidata.org/sparql")

    # Формируем часть VALUES для SPARQL запроса
    values_clause = " ".join(f"wd:{qid}" for qid in q_ids)

    # SPARQL-запрос с дополнительными опциональными свойствами
    query = f"""
    SELECT ?item ?itemLabel ?description ?image ?instanceOf ?instanceOfLabel ?coordinates ?admin ?adminLabel ?website ?inception WHERE {{
      VALUES ?item {{ {values_clause} }}

      OPTIONAL {{
        ?item schema:description ?description .
        FILTER(LANG(?description) = "{lang}")
      }}
      OPTIONAL {{ ?item wdt:P18 ?image. }}          # Изображение
      OPTIONAL {{ ?item wdt:P31 ?instanceOf. }}      # Тип объекта (instance of)
      OPTIONAL {{ ?item wdt:P625 ?coordinates. }}    # Географические координаты
      OPTIONAL {{ ?item wdt:P131 ?admin. }}          # Административное деление
      OPTIONAL {{ ?item wdt:P856 ?website. }}        # Официальный сайт
      OPTIONAL {{ ?item wdt:P571 ?inception. }}      # Дата основания

      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{lang},en". }}
    }}
    """

    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)

    results = sparql.query().convert()
    return results["results"]["bindings"]


# Пример использования функции
if __name__ == "__main__":
    q_ids = ["Q42", "Q5", "Q64"]  # Q42 - Дуглас Адамс, Q5 - Человек, Q64 - Берлин
    entities = get_entities_data(q_ids)

    for entity in entities:
        entity_id = entity["item"]["value"].split("/")[-1]
        label = entity.get("itemLabel", {}).get("value", "Нет метки")
        description = entity.get("description", {}).get("value", "Нет описания")
        image = entity.get("image", {}).get("value", "Нет изображения")

        print(f"ID: {entity_id}\nМетка: {label}\nОписание: {description}\nИзображение: {image}\n")
