"""扩展模块路由：把 M2 / B / C / 验收驾驶舱挂到同一个 HTTP 服务上。

约定：每个 mod_*.py 暴露 handle_get(handler, path) / handle_post(handler, path)，
真正处理了请求返回 True，否则返回 False，交给主服务继续匹配。这样 server.py
只需要两行钩子，M1 的既有路由完全不受影响。

模块以“可缺省”方式加载：某个 mod_*.py 尚未完成、语法有误或缺少钩子时，
只跳过该模块并打印一行提示，不阻塞其他模块、单元测试和主服务启动。
"""

from __future__ import annotations

import importlib

MODULE_NAMES = ("mod_m2", "mod_ai", "mod_ip", "mod_evidence")


def _collect() -> tuple[tuple, tuple]:
    get_routers: list = []
    post_routers: list = []
    for name in MODULE_NAMES:
        try:
            module = importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - 单个模块异常不应拖垮主服务
            print("[extensions] 跳过模块 %s：%s" % (name, exc), flush=True)
            continue
        getter = getattr(module, "handle_get", None)
        poster = getattr(module, "handle_post", None)
        if callable(getter):
            get_routers.append(getter)
        else:
            print("[extensions] 模块 %s 缺少 handle_get，已跳过" % name, flush=True)
        if callable(poster):
            post_routers.append(poster)
        else:
            print("[extensions] 模块 %s 缺少 handle_post，已跳过" % name, flush=True)
    return tuple(get_routers), tuple(post_routers)


GET_ROUTERS, POST_ROUTERS = _collect()


def handle(handler, method: str, path: str) -> bool:
    routers = GET_ROUTERS if method == "GET" else POST_ROUTERS
    for router in routers:
        if router(handler, path):
            return True
    return False
