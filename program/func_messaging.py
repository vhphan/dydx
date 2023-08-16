import requests

from program.constants import BOT_TOKEN, CHAT_ID


def send_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={message}"
    res = requests.get(url)
    if res.status_code == 200:
        return "sent"
    return "failed"


if __name__ == '__main__':
    send_message('Hello World!')