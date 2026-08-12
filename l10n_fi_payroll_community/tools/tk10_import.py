import requests


class Tk10Import:
    def fetch(self, lang):
        url = (f'https://data.stat.fi/api/classifications/v2/classifications/ammatti_17_20210101/'
               f'classificationItems?content=data&format=json&lang={lang}&meta=max')
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            return self._transform(data)
        else:
            raise Exception(f"Failed to fetch data: {response.status_code}")

    def _transform(self, data):
        transformed_data = []
        for item in data:
            transformed_item = {
                'code': item['code'],
                'name': item['classificationItemNames'][0]['name'],
            }
            transformed_data.append(transformed_item)
        return transformed_data
