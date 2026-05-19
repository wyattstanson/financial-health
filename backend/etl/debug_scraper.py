import requests
from bs4 import BeautifulSoup

SESSION = requests.Session()

# Login
resp = SESSION.get('https://www.screener.in/login/')
soup = BeautifulSoup(resp.text, 'html.parser')
csrf = soup.find('input', {'name': 'csrfmiddlewaretoken'})['value']
email = input("Email: ")
import getpass
password = getpass.getpass("Password: ")
SESSION.post('https://www.screener.in/login/', data={
    'username': email, 'password': password,
    'csrfmiddlewaretoken': csrf
}, headers={'Referer': 'https://www.screener.in/login/'})

# Check TCS P&L table row names
resp = SESSION.get('https://www.screener.in/company/TCS/consolidated/')
soup = BeautifulSoup(resp.text, 'html.parser')

section = soup.find('section', {'id': 'profit-loss'})
table = section.find('table')
for tr in table.find_all('tr')[:15]:
    cells = tr.find_all('td')
    if cells:
        print(repr(cells[0].text.strip()))