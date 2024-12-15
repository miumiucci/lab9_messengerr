import tornado.ioloop
import tornado.web
import tornado.websocket
import redis
import threading
import json
import logging

# Настройка логировани
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class ChatWebSocketHandler(tornado.websocket.WebSocketHandler):
    clients = {}  # Словарь для хранения всех подключенных клиентов

    def open(self):
        # Генерация уникального идентификатора клиента
        self.client_id = f"client{len(self.clients) + 1}"
        self.clients[self.client_id] = self
        logging.info(f"New client connected: {self.client_id}. Total clients: {len(self.clients)}")
        self.update_clients_list()

    def on_message(self, message):
        try:
            # Обработка сообщения в формате JSON
            msg_data = json.loads(message)
            text = msg_data.get("text", "").strip()

            if text:
                formatted_message = f"{self.client_id}: {text}"
                logging.info(f"Message received: {formatted_message}")

                # Отправка сообщения всем клиентам
                for client in self.clients.values():
                    client.write_message(formatted_message)

                # Публикация сообщения в Redis
                redis_client.publish("chat_channel", formatted_message)
            else:
                logging.warning("Received an empty message")

        except json.JSONDecodeError:
            logging.error("Invalid message format received")

    def on_close(self):
        # Удаление клиента из списка подключений
        del self.clients[self.client_id]
        logging.info(f"Client {self.client_id} disconnected. Total clients: {len(self.clients)}")
        self.update_clients_list()

    def update_clients_list(self):
        # Отправка обновленного списка подключенных клиентов
        online_clients = list(self.clients.keys())
        update_message = json.dumps({"event": "update_clients", "clients": online_clients})
        for client in self.clients.values():
            client.write_message(update_message)

    def check_origin(self, origin):
        # Разрешаем все кросс-доменные запросы (можно усилить защиту)
        return True


def redis_subscriber(client, callback):
    """Подписка на канал Redis и передача сообщений через callback"""
    pubsub = client.pubsub()
    pubsub.subscribe("chat_channel")
    logging.info("Subscribed to Redis channel 'chat_channel'")
    for message in pubsub.listen():
        if message["type"] == "message":
            callback(message["data"])


def make_app():
    """Создание приложения Tornado"""
    return tornado.web.Application([
        (r"/websocket", ChatWebSocketHandler),
        (r"/(.*)", tornado.web.StaticFileHandler, {"path": "./f", "default_filename": "index.html"}),  # Путь к статическим файлам
    ])


if __name__ == "__main__":
    # Подключение к Redis
    redis_client = redis.StrictRedis(host="localhost", port=6379, decode_responses=True)

    # Callback для передачи сообщений клиентам
    def redis_callback(message):
        loop = tornado.ioloop.IOLoop.current()
        loop.add_callback(lambda: send_message_to_clients(message))

    def send_message_to_clients(message):
        for client in ChatWebSocketHandler.clients.values():
            client.write_message(message)

    # Запуск подписки на Redis в отдельном потоке
    threading.Thread(target=lambda: redis_subscriber(redis_client, redis_callback), daemon=True).start()

    # Запуск Tornado сервера
    app = make_app()
    app.listen(8888)
    logging.info("Server running on http://localhost:8888")
    tornado.ioloop.IOLoop.current().start()

