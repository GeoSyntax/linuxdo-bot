"""机器人主入口。

运行模式：
    # 正式运行（需 .env 里配 TG_BOT_TOKEN）
    python -m linuxdo_bot

    # dry-run：不需 TG token，对真实 linux.do 跑一轮，命中的关键词打印到控制台
    python -m linuxdo_bot --dry-run --keyword python --keyword "ai|llm"

    # 只拉一轮最新（自检采集是否通）
    python -m linuxdo_bot --once
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading

# Windows 控制台默认 GBK，emoji/部分中文会 UnicodeEncodeError；统一切到 UTF-8。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from .commands import CommandRouter
from .config import BotConfig
from .monitor import Monitor
from .store import Store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("linuxdo_bot")


def _dry_run(config: BotConfig, keywords: list[str]) -> None:
    """无需 TG：把订阅设为命令行传入的关键词，采集一轮，命中就打印。"""
    from .corpus import Corpus
    store = Store(":memory:")
    corpus = Corpus(":memory:")
    fake_chat = "dryrun"
    for kw in keywords:
        store.add_subscription(fake_chat, kw)

    def notifier(chat_id: str, text: str) -> None:
        print("\n" + "─" * 56)
        print(text.replace("<b>", "").replace("</b>", "")
                  .replace("<code>", "").replace("</code>", ""))

    logger.info("DRY-RUN：关键词=%s，采集一轮官方 TG 频道…", keywords)
    mon = Monitor(config, store, notifier, corpus=corpus)
    n = mon.poll_once()
    print("\n" + "═" * 56)
    print(f"完成：命中并输出 {n} 条（关键词 {keywords}）；语料库沉淀 {corpus.count()} 篇。")
    print("真实运行会推送到 Telegram。")
    corpus.close()
    store.close()


def _backfill(config: BotConfig, pages: int) -> None:
    from .backfill import run_backfill
    from .corpus import Corpus
    corpus = Corpus(config.db_full_path)
    stats = run_backfill(config, corpus, pages=pages)
    print(f"回填完成：本次新增 {stats['new']} 篇，语料库累计 {stats['corpus_total']} 篇。")
    print("再次运行会从上次进度继续（断点续跑）。")
    corpus.close()


def _fullcrawl(config: BotConfig, limit: int, enumerate_only: bool,
               max_sitemaps: int | None) -> None:
    """全站采集：sitemap 枚举 → frontier 入队 → 逐主题取全文（断点续跑）。"""
    from .corpus import Corpus
    from .fullcrawl import FullCrawler
    corpus = Corpus(config.db_full_path)
    crawler = FullCrawler(config, corpus)

    fr = corpus.frontier_stats()
    if enumerate_only or not fr:
        print(f"枚举全站 sitemap（max_sitemaps={max_sitemaps or '全部43'}）…")
        est = crawler.enumerate_site(max_sitemaps=max_sitemaps)
        print(f"枚举完成：发现 {est['discovered']}，新登记 {est['new']}，"
              f"frontier={est['frontier']}")
        if enumerate_only:
            corpus.close()
            return

    print(f"开始详情采集，本次上限 {limit} 篇（限速 {config.requests_per_second} 请求/秒）…")
    stats = crawler.crawl_details(limit)
    print(f"本次：处理 {stats['processed']}，成功 {stats['ok']}，失败 {stats['failed']}，"
          f"失效 {stats.get('gone', 0)}；语料库累计 {stats['corpus_total']} 篇。")
    print(f"frontier 状态：{stats['frontier']}")
    print("再次运行会从 frontier 的 pending 继续（断点续跑）。")
    corpus.close()


def _reindex(config: BotConfig) -> None:
    from .corpus import Corpus
    from .rag import get_embedder, Retriever
    corpus = Corpus(config.db_full_path)
    r = Retriever(corpus, get_embedder(config))
    stats = r.reindex()
    print(f"建索引完成：本次 {stats['indexed']} 篇，索引累计 {stats['total']} 条向量。")
    corpus.close()


def _ask_once(config: BotConfig, question: str) -> None:
    """离线问答自检：对已建索引的语料库问一个问题。"""
    import re
    from .corpus import Corpus
    from .rag import get_embedder, Retriever, RagEngine
    corpus = Corpus(config.db_full_path)
    engine = RagEngine(Retriever(corpus, get_embedder(config)), config)
    print(f"Q: {question}\n")
    print(re.sub(r"<[^>]+>", "", engine.ask(question)))
    corpus.close()


def _run_bot(config: BotConfig) -> None:
    if not config.tg_token:
        raise SystemExit("缺少 TG_BOT_TOKEN。请在 .env 配置，或用 --dry-run 无token验证。")

    from .telegram import TelegramClient
    tg = TelegramClient(config.tg_token, config.tg_api_base)
    me = tg.get_me()
    logger.info("机器人已连接：@%s", me.get("username"))

    from .corpus import Corpus
    from .rag import get_embedder, Retriever, RagEngine
    store = Store(config.db_full_path)
    corpus = Corpus(config.db_full_path)

    # RAG 引擎（/ask）：语料库 + embedder + LLM
    engine = RagEngine(Retriever(corpus, get_embedder(config)), config)

    # 监控线程：命中订阅 → 推送；同时沉淀语料库
    monitor = Monitor(config, store,
                      notifier=lambda cid, text: tg.send_message(cid, text),
                      corpus=corpus)
    t = threading.Thread(target=monitor.run_forever, daemon=True)
    t.start()

    # /latest 需即时采集：给命令路由一个回调
    def fetch_latest(n: int):
        from zhihu_crawler.client import ZhihuClient
        with ZhihuClient(monitor._crawler_config) as client:
            src = monitor._make_source(client)
            try:
                return list(src.fetch(config.categories[0], n))
            finally:
                src.close()

    router = CommandRouter(store, fetch_latest=fetch_latest, ask_fn=engine.ask)

    # 主线程：长轮询收命令 + inline 按钮回调
    from .presets import keyword_buttons, charity_buttons
    logger.info("开始接收命令（Ctrl+C 退出）")
    offset = None
    try:
        while True:
            for upd in tg.get_updates(offset=offset, timeout=30):
                offset = upd["update_id"] + 1
                # inline 按钮点击
                cq = upd.get("callback_query")
                if cq:
                    chat_id = str(cq["message"]["chat"]["id"])
                    note = router.handle_callback(chat_id, cq.get("data", ""))
                    tg.answer_callback(cq["id"], note)
                    continue
                msg = upd.get("message") or upd.get("channel_post")
                if not msg or "text" not in msg:
                    continue
                chat_id = str(msg["chat"]["id"])
                reply = router.handle(chat_id, msg["text"])
                if reply == "QUICK":
                    tg.send_message(chat_id, "⚡ 一键订阅热门关键词：",
                                    inline_keyboard=keyword_buttons())
                    cb = charity_buttons()
                    if cb:
                        tg.send_message(chat_id, "👥 关注公益大佬：", inline_keyboard=cb)
                else:
                    tg.send_message(chat_id, reply, disable_preview=True)
    except KeyboardInterrupt:
        logger.info("停止中…")
        monitor.stop()
        store.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="linux.do 关键词监控 Telegram 机器人")
    ap.add_argument("--dry-run", action="store_true", help="不需 TG token，采集一轮并打印命中")
    ap.add_argument("--keyword", action="append", default=[], help="dry-run 关键词（可多次）")
    ap.add_argument("--once", action="store_true", help="只采集一轮就退出（自检用）")
    ap.add_argument("--backfill", action="store_true", help="历史回填语料库（断点续跑）")
    ap.add_argument("--pages", type=int, default=20, help="回填页数（每页约15条）")
    ap.add_argument("--reindex", action="store_true", help="给语料库文档建/补 RAG 向量索引")
    ap.add_argument("--ask", default="", help="离线问答自检：/ask 一个问题（无需 TG token）")
    ap.add_argument("--fullcrawl", action="store_true",
                    help="全站采集：sitemap 枚举 + 逐主题取全文（断点续跑，无需 token）")
    ap.add_argument("--enumerate-only", action="store_true",
                    help="仅枚举 sitemap 把 topic_id 登记进 frontier，不采详情")
    ap.add_argument("--limit", type=int, default=200, help="全站采集本次详情上限（默认200）")
    ap.add_argument("--max-sitemaps", type=int, default=None,
                    help="枚举时最多拉几个子图（默认全部43个；调试可设小）")
    args = ap.parse_args()

    config = BotConfig.load()

    if args.dry_run:
        _dry_run(config, args.keyword or ["python"])
    elif args.backfill:
        _backfill(config, args.pages)
    elif args.reindex:
        _reindex(config)
    elif args.ask:
        _ask_once(config, args.ask)
    elif args.fullcrawl or args.enumerate_only:
        _fullcrawl(config, limit=args.limit, enumerate_only=args.enumerate_only,
                   max_sitemaps=args.max_sitemaps)
    elif args.once:
        from .corpus import Corpus
        store = Store(":memory:")
        corpus = Corpus(":memory:")
        mon = Monitor(config, store, notifier=lambda c, t: print(t), corpus=corpus)
        print(f"采集一轮完成，命中 {mon.poll_once()} 条，语料库 {corpus.count()} 篇")
        store.close(); corpus.close()
    else:
        _run_bot(config)


if __name__ == "__main__":
    main()
