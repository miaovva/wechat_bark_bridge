from flask import Flask, request
import requests

import logging
import threading
import time


log = logging.getLogger("werkzeug")
log.disabled = True

app = Flask(__name__)


# Token 类，用于管理每个 token 的状态、内容和定时任务
class TokenManager:
    def __init__(self, token):
        self.token = token
        self.push_status = True  # 初始状态为启用推送
        self.messages = []  # 存储每个 token 的消息
        self.reset_timer = None  # 5 分钟重置状态的定时器
        self.push_timer = None  # 20 秒延迟推送的定时器
        self.cancel_reset_flag = False  # 用于取消5分钟倒计时

    def add_message(self, message_data):
        copy_message_data = message_data
        msg, title = (message_data["msg"], message_data["title"])

        # 处理内容包含发送用户的情况
        if title + ":" in msg:
            msg = msg.replace(title + ":", "")
            copy_message_data["msg"] = msg

        # 更新单个发送用户最新消息
        if len(self.messages) == 0:
            self.messages.append(copy_message_data)
        else:
            overwrite_flag = False
            current_messages = self.messages
            for index, message in enumerate(current_messages):
                if message["title"] == copy_message_data["title"]:
                    self.messages[index] = copy_message_data
                    overwrite_flag = True
                    break
            if not overwrite_flag:
                self.messages.append(copy_message_data)

    def clear_messages(self):
        self.messages = []

    def set_push_status(self, status):
        self.push_status = status

    def start_reset_timer(self, reset_callback):
        if self.reset_timer is None:
            self.reset_timer = threading.Thread(target=reset_callback, daemon=True)
            self.reset_timer.start()

    def start_push_timer(self, push_callback):
        if self.push_timer is None:
            self.push_timer = threading.Timer(20.0, push_callback)
            self.push_timer.start()

    def cancel_reset_timer(self):
        self.cancel_reset_flag = True
        self.reset_timer = None

    def reset_push_timer(self):
        self.push_timer = None


# 创建一个全局的 token 管理器字典，保存所有 token 对象
token_managers = {}
data_lock = threading.Lock()


# 初始化并获取 token 对象
def get_token_manager(token):
    with data_lock:
        if token not in token_managers:
            token_managers[token] = TokenManager(token)
        return token_managers[token]


# 推送消息到推送服务器的函数
def push_message(token_manager):
    # 如已停止推送，清空消息内容
    if not token_manager.push_status:
        token_manager.clear_messages()  # 如果推送被暂停，清空消息队列
        return
    if token_manager.messages:
        token = token_manager.token
        for message in token_manager.messages:
            msg, title, group, url, icon = (
                message["msg"],
                message["title"],
                message["group"],
                message["url"],
                message["icon"],
            )
            # 推送到服务器
            r = requests.get(
                "https://api.day.app/{}/{}?title={}&group={}&url={}&icon={}&level=active".format(
                    token, msg, title, group, url, icon
                )
            )
            print(f"Message for {token_manager.token} pushed")
        # 重置
        token_manager.clear_messages()
        token_manager.reset_push_timer()


def start_token_push(token_manager):
    token_manager.set_push_status(True)
    token_manager.reset_push_timer()


def stop_token_push(token_manager):
    token_manager.set_push_status(False)
    token_manager.reset_push_timer()


# 重置推送状态的函数
def reset_push_status(token_manager):
    print(f"Token {token_manager.token} 's push status will be reset in 5 mins")
    for _ in range(300):  # 倒计时 5 分钟 (300秒)
        time.sleep(1)  # 每秒检查一次
        if token_manager.cancel_reset_flag:  # 如果定时器被取消
            token_manager.cancel_reset_flag = False
            start_token_push(token_manager)
            print(
                f"Token {token_manager.token}'s push status reset process has been canceled, now push on."
            )
            return
    start_token_push(token_manager)
    token_manager.reset_timer = None
    print(f"Token {token_manager.token}'s push status has been reset.")


@app.route("/")
def hello_world():
    return "<p>Hello, World!</p>"


@app.route("/push")
def forward_notificatiobn():
    token = request.args.get("token", None)
    if not token:
        return "参数错误1", 400

    token_manager = get_token_manager(token)

    if not token_manager.push_status:
        return "当前已停止推送"

    title = request.args.get("title", None)
    msg = request.args.get("msg", None)
    from_ = request.args.get("from", "fchat")
    group = request.args.get("group", "fchat")
    url = request.args.get("url", "fchat://")
    icon = request.args.get(
        "icon", "https://s2.loli.net/2024/10/11/1hRNIbjcCSke5Zy.png"
    )

    if not title or not msg:
        return "参数错误2", 400

    token_manager.add_message(
        {
            "from": from_,
            "title": title,
            "msg": msg,
            "group": group,
            "url": url,
            "icon": icon,
        }
    )

    if token_manager.push_timer is None:
        token_manager.start_push_timer(lambda: push_message(token_manager))
        return "消息已进入队列，20秒后推送最新消息"

    return "消息已进入队列，20秒内推送最新消息"


@app.route("/stop")
def stop_push():
    token = request.args.get("token", None)
    if not token:
        return "参数错误3", 400

    token_manager = get_token_manager(token)

    stop_token_push(token_manager)
    token_manager.start_reset_timer(
        lambda: reset_push_status(token_manager)
    )  # 启动倒计时5分钟重置

    return "已暂停推送"


@app.route("/start")
def start_push():
    token = request.args.get("token", None)
    if not token:
        return "参数错误4", 400

    token_manager = get_token_manager(token)

    if token_manager.reset_timer:
        token_manager.cancel_reset_timer()

    return "已启用推送"


if __name__ == "__main__":
    app.run()
