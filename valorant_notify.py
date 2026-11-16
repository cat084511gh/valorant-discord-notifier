"""Valorant の新しい試合を検知して Discord Webhook に通知するスクリプト。

HenrikDev API (非公式) を使って最新の試合を取得し、
前回通知した試合 ID (state/last_match.json) と比較して新しい試合だけ通知する。
外部ライブラリ不要 (Python 3.9+ 標準ライブラリのみ)。

環境変数:
  HENRIK_API_KEY       HenrikDev API キー (必須)
  DISCORD_WEBHOOK_URL  Discord Webhook URL (必須)
  VAL_NAME             Riot ID の名前部分 (例: 年上お姉さんに依存されたい)
  VAL_TAG              Riot ID のタグ部分 (例: blitz)
  VAL_REGION           リージョン (日本は ap) 既定: ap
  STATE_FILE           状態ファイルのパス 既定: state/last_match.json
  DRY_RUN              1 にすると Discord に送らず内容を表示するだけ
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_BASE = "https://api.henrikdev.xyz"
MAX_NOTIFY = 5  # 一度に通知する最大試合数 (久しぶりの実行で大量に流れないように)
USER_AGENT = "valorant-discord-notifier/1.0"


def env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        sys.exit(f"環境変数 {name} が設定されていません")
    return value or ""


def http_get_json(url: str, api_key: str):
    req = urllib.request.Request(
        url, headers={"Authorization": api_key, "User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"API エラー {e.code}: {url}\n{body}") from e


def post_discord(webhook_url: str, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        res.read()


def q(s: str) -> str:
    return urllib.parse.quote(s, safe="")


def fetch_matches(region: str, name: str, tag: str, api_key: str) -> list[dict]:
    url = f"{API_BASE}/valorant/v3/matches/{q(region)}/{q(name)}/{q(tag)}?size=10"
    return http_get_json(url, api_key).get("data") or []


def fetch_mmr_history(region: str, name: str, tag: str, api_key: str) -> dict[str, dict]:
    """match_id -> MMR 履歴エントリ。取得失敗時は空 (ランク情報なしで通知する)。"""
    url = f"{API_BASE}/valorant/v1/mmr-history/{q(region)}/{q(name)}/{q(tag)}"
    try:
        data = http_get_json(url, api_key).get("data") or []
    except Exception as e:  # noqa: BLE001
        print(f"MMR 履歴の取得に失敗 (無視して続行): {e}", file=sys.stderr)
        return {}
    return {d.get("match_id"): d for d in data if d.get("match_id")}


def load_state(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find_player(match: dict, name: str, tag: str) -> dict | None:
    players = (match.get("players") or {}).get("all_players") or []
    for p in players:
        if (p.get("name") or "").casefold() == name.casefold() and (
            p.get("tag") or ""
        ).casefold() == tag.casefold():
            return p
    return None


def build_embed(match: dict, player: dict, mmr: dict | None, name: str, tag: str) -> dict:
    meta = match.get("metadata") or {}
    stats = player.get("stats") or {}
    team_key = (player.get("team") or "").lower()
    teams = match.get("teams") or {}
    my_team = teams.get(team_key) if isinstance(teams, dict) else None

    mode = meta.get("mode") or "?"
    map_name = meta.get("map") or "?"
    rounds = meta.get("rounds_played") or 0

    # 勝敗判定 (デスマッチ等はチーム情報がないので結果不明扱い)
    if my_team and my_team.get("has_won") is not None:
        won = bool(my_team.get("has_won"))
        drew = my_team.get("rounds_won") == my_team.get("rounds_lost")
        if drew and not won:
            result, color = "引き分け", 0x95A5A6
        elif won:
            result, color = "勝利", 0x2ECC71
        else:
            result, color = "敗北", 0xE74C3C
        score_text = f"{my_team.get('rounds_won', '?')} - {my_team.get('rounds_lost', '?')}"
    else:
        result, color = "試合終了", 0x3498DB
        score_text = "-"

    k, d, a = stats.get("kills", 0), stats.get("deaths", 0), stats.get("assists", 0)
    kd = f"{k / d:.2f}" if d else f"{k:.2f}"
    acs = round(stats.get("score", 0) / rounds) if rounds else "-"
    shots = sum(stats.get(s, 0) or 0 for s in ("headshots", "bodyshots", "legshots"))
    hs = f"{(stats.get('headshots', 0) or 0) / shots * 100:.0f}%" if shots else "-"

    fields = [
        {"name": "エージェント", "value": player.get("character") or "?", "inline": True},
        {"name": "スコア", "value": score_text, "inline": True},
        {"name": "K / D / A", "value": f"{k} / {d} / {a} (K/D {kd})", "inline": True},
        {"name": "ACS", "value": str(acs), "inline": True},
        {"name": "HS%", "value": hs, "inline": True},
    ]

    if mmr:
        change = mmr.get("mmr_change_to_last_game")
        change_text = f"{change:+d} RR" if isinstance(change, int) else ""
        rank_text = f"{mmr.get('currenttierpatched', '?')} ({mmr.get('ranking_in_tier', '?')} RR)"
        fields.append(
            {"name": "ランク", "value": f"{rank_text} {change_text}".strip(), "inline": True}
        )
    elif player.get("currenttier_patched"):
        fields.append(
            {"name": "ランク", "value": player["currenttier_patched"], "inline": True}
        )

    match_id = meta.get("matchid") or ""
    embed = {
        "title": f"{result} — {map_name} ({mode})",
        "url": f"https://tracker.gg/valorant/match/{match_id}" if match_id else None,
        "color": color,
        "author": {
            "name": f"{name}#{tag}",
            "url": f"https://tracker.gg/valorant/profile/riot/{q(name + '#' + tag)}/overview",
        },
        "fields": fields,
    }
    thumb = (player.get("assets") or {}).get("agent", {}).get("small")
    if thumb:
        embed["thumbnail"] = {"url": thumb}
    start = meta.get("game_start")
    if isinstance(start, (int, float)):
        embed["timestamp"] = datetime.fromtimestamp(start, tz=timezone.utc).isoformat()
    return {k2: v for k2, v in embed.items() if v is not None}


def main() -> None:
    api_key = env("HENRIK_API_KEY", required=True)
    dry_run = env("DRY_RUN") == "1"
    webhook = env("DISCORD_WEBHOOK_URL", required=not dry_run)
    name = env("VAL_NAME", required=True)
    tag = env("VAL_TAG", required=True)
    region = env("VAL_REGION", "ap")
    state_path = Path(env("STATE_FILE", "state/last_match.json"))

    matches = fetch_matches(region, name, tag, api_key)
    if not matches:
        print("試合が取得できませんでした (戦績なし or 非公開)")
        return

    if env("TEST_NOTIFY") == "1":
        # テスト送信: 最新の 1 試合を通知するだけ (状態ファイルは変更しない)
        latest = matches[0]
        mid = (latest.get("metadata") or {}).get("matchid")
        player = find_player(latest, name, tag)
        if not player:
            sys.exit(f"試合 {mid} にプレイヤーが見つかりません")
        mmr = fetch_mmr_history(region, name, tag, api_key).get(mid)
        payload = {"embeds": [build_embed(latest, player, mmr, name, tag)]}
        if dry_run:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            post_discord(webhook, payload)
            print(f"テスト通知を送信しました: {mid}")
        return

    state = load_state(state_path)
    last_id = state.get("last_match_id")
    latest_id = (matches[0].get("metadata") or {}).get("matchid")

    if not last_id:
        # 初回は過去の試合を通知せず、最新 ID を記録するだけ
        print(f"初回実行: 最新試合 {latest_id} を記録しました (通知なし)")
        save_state(state_path, {"last_match_id": latest_id})
        return

    # matches は新しい順。前回 ID より新しいものを集める
    new_matches = []
    for m in matches:
        if (m.get("metadata") or {}).get("matchid") == last_id:
            break
        new_matches.append(m)

    if not new_matches:
        print("新しい試合はありません")
        return

    new_matches = list(reversed(new_matches[:MAX_NOTIFY]))  # 古い順に通知
    mmr_map = fetch_mmr_history(region, name, tag, api_key)

    for m in new_matches:
        mid = (m.get("metadata") or {}).get("matchid")
        player = find_player(m, name, tag)
        if not player:
            print(f"試合 {mid} にプレイヤーが見つかりません (スキップ)")
            continue
        payload = {"embeds": [build_embed(m, player, mmr_map.get(mid), name, tag)]}
        if dry_run:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            post_discord(webhook, payload)
            print(f"通知しました: {mid}")

    if not dry_run:
        save_state(state_path, {"last_match_id": latest_id})


if __name__ == "__main__":
    main()
