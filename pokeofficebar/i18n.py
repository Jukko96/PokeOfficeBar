"""UI strings in Korean and English.

Save files always store the English keys for rarity and nature — only the
display is translated, so switching languages never rewrites or invalidates a
save.
"""

from __future__ import annotations

_LANG = "ko"


def set_lang(lang: str) -> None:
    global _LANG
    _LANG = lang if lang in ("ko", "en") else "ko"


def lang() -> str:
    return _LANG


def t(key: str, **kw) -> str:
    entry = STRINGS.get(key)
    if entry is None:
        return key
    text = entry.get(_LANG) or entry.get("en") or key
    text = text.format(**kw) if kw else text
    return text


def rarity(name: str) -> str:
    return RARITY.get(name, {}).get(_LANG, name)


def nature(name: str) -> str:
    return NATURE.get(name, {}).get(_LANG, name)


RARITY = {
    "Common":    {"ko": "흔함",      "en": "Common"},
    "Uncommon":  {"ko": "조금 귀함",  "en": "Uncommon"},
    "Rare":      {"ko": "귀함",      "en": "Rare"},
    "Very Rare": {"ko": "매우 귀함",  "en": "Very Rare"},
    "Legendary": {"ko": "전설",      "en": "Legendary"},
}

# Korean display labels for personality.
_NATURE_KO = {
    "Hardy": "노력", "Lonely": "외로움", "Brave": "용감", "Adamant": "고집",
    "Naughty": "개구쟁이", "Bold": "대담", "Docile": "온순", "Relaxed": "무사태평",
    "Impish": "장난꾸러기", "Lax": "촐랑", "Timid": "겁쟁이", "Hasty": "성급",
    "Serious": "성실", "Jolly": "명랑", "Naive": "천진난만", "Modest": "조심",
    "Mild": "의젓", "Quiet": "냉정", "Bashful": "수줍음", "Rash": "덜렁",
    "Calm": "차분", "Gentle": "얌전", "Sassy": "건방", "Careful": "신중",
    "Quirky": "변덕",
}
NATURE = {k: {"ko": v, "en": k} for k, v in _NATURE_KO.items()}


STRINGS: dict[str, dict[str, str]] = {
    "office.egg": {"ko": "알이 자라고 있습니다.", "en": "Your egg is growing."},
    "office.progress": {"ko": "{done} / {goal} 포인트 — {step}", "en": "{done} / {goal} points {step}"},
    "office.balance": {"ko": "사용 가능 {balance} 포인트", "en": "{balance} points available"},
    "office.status": {"ko": "자동으로 성장 중", "en": "Growing automatically"},
    "office.paused": {"ko": "화면 잠금 중 · 시간 적립 일시정지", "en": "Screen locked · timer paused"},
    "office.total": {"ko": "누적 적립 {points}포인트 · 육성 완료 {count}마리", "en": "{points} points earned · {count} companions completed"},
    "office.shop": {"ko": "상점 — 사용 가능 {balance} 포인트", "en": "Shop — {balance} points available"},
    "office.price": {"ko": "{desc}   ·   {price} 포인트", "en": "{desc} · {price} points"},
    # --- shell ---
    "app.title":        {"ko": "PokeOfficeBar",   "en": "PokeOfficeBar"},
    "tab.home":         {"ko": "홈",          "en": "Home"},
    "tab.pokedex":      {"ko": "도감",        "en": "Pokedex"},
    "tab.bag":          {"ko": "가방",        "en": "Bag"},
    "tab.shop":         {"ko": "상점",        "en": "Shop"},
    "tab.berry":        {"ko": "화분",        "en": "Berries"},
    "tab.expedition":   {"ko": "탐험대",      "en": "Trips"},
    "tab.settings":     {"ko": "설정",        "en": "Settings"},

    "berry.title": {"ko": "나무열매 화분", "en": "Berry planter"},
    "berry.hint": {"ko": "심은 열매는 화면을 켜고 일하는 동안 자랍니다. 수확하면 상점 포인트나 이상한 사탕을 받습니다.",
                   "en": "Berries grow while your desktop is unlocked. Harvest for shop points or a Rare Candy."},
    "berry.empty": {"ko": "심을 수 있는 빈 화분", "en": "Ready to plant"},
    "berry.slot": {"ko": "{number}번 화분", "en": "Pot {number}"},
    "berry.locked": {"ko": "잠김", "en": "Locked"},
    "berry.unlock": {"ko": "{price}포인트로 해금", "en": "Unlock for {price} points"},
    "berry.unlocked": {"ko": "{number}번 화분을 해금했습니다.", "en": "Unlocked pot {number}."},
    "berry.growing": {"ko": "자라는 중 · {percent}%", "en": "Growing · {percent}%"},
    "berry.ripe": {"ko": "수확할 수 있습니다", "en": "Ready to harvest"},
    "berry.plant": {"ko": "심기", "en": "Plant"},
    "berry.wait": {"ko": "자라는 중", "en": "Growing"},
    "berry.harvest": {"ko": "수확하기", "en": "Harvest"},
    "berry.planted": {"ko": "나무열매를 심었습니다.", "en": "Planted a berry."},
    "berry.plant_all": {"ko": "모두 심기", "en": "Plant all"},
    "berry.plant_result": {"ko": "빈 화분 {count}개에 심었습니다.", "en": "Planted in {count} pots."},
    "berry.harvested": {"ko": "수확 보상 · {item} ×{amount}", "en": "Harvest reward · {item} ×{amount}"},
    "berry.harvest_all": {"ko": "익은 열매 모두 수확", "en": "Harvest all ripe berries"},
    "berry.batch_result": {"ko": "화분 {count}개 수확 · {rewards}", "en": "Harvested {count} pots · {rewards}"},
    "berry.batch_points": {"ko": "상점 포인트 +{points}", "en": "+{points} shop points"},
    "berry.batch_candy": {"ko": "이상한 사탕 ×{candies}", "en": "Rare Candy ×{candies}"},

    "expedition.title": {"ko": "졸업생 탐험대", "en": "Graduate expeditions"},
    "expedition.hint": {
        "ko": "목적지 등급 이상의 졸업생을 보내고, 귀환하면 받기를 눌러 보상을 받으세요. 같은 종의 일반과 이로치는 귀환 후 24시간의 휴식을 공유합니다.",
        "en": "Send a graduate who meets the destination's rarity and collect their reward on return. Normal and Shiny forms of the same species share a 24-hour rest.",
    },
    "expedition.meadow": {"ko": "들꽃 초원", "en": "Wildflower Meadow"},
    "expedition.forest": {"ko": "고요한 숲", "en": "Quiet Woods"},
    "expedition.lake": {"ko": "물안개 호수", "en": "Mist Lake"},
    "expedition.cave": {"ko": "수정 동굴", "en": "Crystal Cavern"},
    "expedition.summit": {"ko": "구름 봉우리", "en": "Cloud Summit"},
    "expedition.details": {"ko": "{rarity} 이상 · {minutes}분 · {points}점 · 이로치 +{bonus}점",
                           "en": "{rarity} or higher · {minutes} min · {points} pts · shiny +{bonus}"},
    "expedition.choose": {"ko": "졸업생 선택", "en": "Choose a graduate"},
    "expedition.none": {"ko": "보낼 수 있는 졸업생 없음", "en": "No eligible graduates"},
    "expedition.active_choice": {"ko": "탐험 진행 중", "en": "Expedition in progress"},
    "expedition.send": {"ko": "보내기", "en": "Send"},
    "expedition.claim": {"ko": "받기", "en": "Collect"},
    "expedition.reward_pending": {"ko": "받을 보상이 있습니다", "en": "Reward ready to collect"},
    "expedition.reward_claimed": {"ko": "탐험 보상 · 상점 포인트 +{points}", "en": "Expedition reward · +{points} shop points"},
    "expedition.shiny_name": {"ko": "{name} (이로치)", "en": "{name} (Shiny)"},
    "expedition.active": {"ko": "{name} 탐험 중 · {left} 남음", "en": "{name} exploring · {left} left"},
    "expedition.paused": {"ko": "{name} 탐험 일시정지 · {left} 남음",
                          "en": "{name} paused · {left} left"},
    "expedition.last": {"ko": "최근 귀환 · {name} · +{points}점", "en": "Last return · {name} · +{points} pts"},
    "expedition.last_pending": {"ko": "최근 귀환 · {name} · 받을 보상 {points}점",
                                "en": "Last return · {name} · {points} pts to collect"},
    "expedition.rest": {"ko": "재출발까지 {left}", "en": "Available again in {left}"},
    "expedition.rest_hours": {"ko": "{hours}시간 {minutes}분", "en": "{hours}h {minutes}m"},
    "expedition.destinations": {"ko": "목적지", "en": "Destinations"},
    "expedition.resting": {"ko": "휴식 중 {count}종", "en": "Resting ({count})"},
    "expedition.rest_empty": {"ko": "휴식 중인 포켓몬이 없습니다.", "en": "No Pokemon are resting."},
    "expedition.rest_both": {"ko": "{name} · 일반·이로치", "en": "{name} · Normal and Shiny"},
    "expedition.ready_at": {"ko": "{when}부터 재출발 가능", "en": "Available again at {when}"},
    "expedition.history": {"ko": "탐험 내역", "en": "Recent trips"},
    "expedition.history_empty": {"ko": "아직 귀환한 탐험이 없습니다.", "en": "No trips have returned yet."},
    "expedition.history_pending": {"ko": "보상 {points}점 · 수령 대기", "en": "{points} pts · Unclaimed"},
    "expedition.history_claimed": {"ko": "보상 {points}점 · 수령 완료", "en": "{points} pts · Collected"},
    "expedition.return": {"ko": "{name} 탐험 귀환 · 보상 {points}점 받기",
                          "en": "{name} returned · {points} points to collect"},
    "common.loading":   {"ko": "불러오는 중…", "en": "Loading..."},
    "gift.found": {"ko": "포켓몬이 선물을 주워왔습니다. 눌러서 받아주세요!", "en": "Your companion found a gift. Click to collect!"},
    "gift.claim": {"ko": "선물 받기", "en": "Collect gift"},
    "gift.points": {"ko": "상점 포인트", "en": "Shop points"},
    "gift.received": {"ko": "{item} ×{amount} 획득", "en": "Received {amount} × {item}."},
    "gift.retry": {"ko": "선물을 저장하지 못했습니다. 다시 받아주세요.", "en": "Could not save the gift. Please collect it again."},
    "common.problem":   {"ko": "문제 발생",    "en": "Problem"},

    # --- companion ---
    "egg.name":         {"ko": "알",          "en": "Egg"},
    "egg.shiny":        {"ko": "이로치 알 ✨", "en": "Shiny egg ✨"},
    "home.line":        {"ko": "진화 라인:  {names}", "en": "Line:  {names}"},
    "home.subtitle":    {"ko": "{rarity} · {nature} 성격",
                         "en": "{rarity} · {nature} nature"},
    "step.hatch":       {"ko": "부화까지",     "en": "until hatch"},
    "step.evolve":      {"ko": "진화까지",     "en": "until evolution"},
    "step.graduate":    {"ko": "졸업까지",     "en": "until graduation"},

    # --- usage ---
    "left.hm":          {"ko": "{h}시간 {m}분",  "en": "{h}h {m}m"},
    "left.m":           {"ko": "{m}분",         "en": "{m}m"},
    "left.d":           {"ko": "{d}일 {h}시간",  "en": "{d}d {h}h"},
    "left.now":         {"ko": "곧 초기화",      "en": "resetting"},
    "eta.official":     {"ko": "에이전트 보고 기준",  "en": "as reported by the agent"},
    "eta.none":         {"ko": "아직 사용 기록 없음",     "en": "no activity yet"},
    "eta.reached":      {"ko": "예산 이미 도달",         "en": "budget already reached"},
    "eta.at":           {"ko": "{time}에 예산 도달 예상", "en": "fills at {time}"},
    "eta.never":        {"ko": "이번 구간 안에는 도달 안 함",
                         "en": "won't fill before this window resets"},

    # --- pokedex ---
    "dex.title":        {"ko": "도감 — {n}종 확인", "en": "Pokedex — {n} species seen"},
    "dex.empty":        {"ko": "아직 없습니다. 첫 알이 아직 따뜻해지는 중입니다.",
                         "en": "Nothing yet. Your first egg is still warming up."},
    "dex.log.title":    {"ko": "포획 기록 — {n}마리 키움", "en": "Catch log — {n} raised"},
    "dex.log.empty":    {"ko": "아직 졸업한 포켓몬이 없습니다.", "en": "No graduates yet."},
    "dex.pin.hint":     {"ko": "칸을 누르면 트레이 아이콘과 데스크톱 펫에 고정됩니다.",
                         "en": "Click a cell to pin it to the tray icon and desktop pet."},
    "dex.pin.current":  {"ko": "고정: {name}",   "en": "Pinned: {name}"},
    "dex.pin.clear":    {"ko": "고정 해제",       "en": "Unpin"},
    "dex.tab.dex":      {"ko": "도감",        "en": "Pokédex"},
    "dex.tab.log":      {"ko": "포획 기록",   "en": "Catch log"},
    "dex.raising":      {"ko": "키우는 중",   "en": "RAISING"},

    # --- bag ---
    "bag.title":        {"ko": "가방",        "en": "Bag"},
    "bag.use":          {"ko": "사용",        "en": "Use"},
    "bag.none":         {"ko": "가진 게 없습니다.", "en": "You have none of those."},
    "bag.sale.button": {"ko": "판매 · {points}점", "en": "Sell · {points} pts"},
    "bag.sale.title": {"ko": "아이템 판매", "en": "Sell item"},
    "bag.sale.stock": {"ko": "보유 {count}개 · 개당 {points}점", "en": "Owned {count} · {points} points each"},
    "bag.sale.quantity": {"ko": "판매 수량", "en": "Quantity"},
    "bag.sale.all": {"ko": "전부", "en": "All"},
    "bag.sale.total": {"ko": "받을 포인트 {points}점", "en": "You receive {points} points"},
    "bag.sale.confirm": {"ko": "판매", "en": "Sell"},
    "bag.sale.cancel": {"ko": "취소", "en": "Cancel"},
    "bag.sale.invalid_quantity": {"ko": "보유 수량을 확인해 주세요.", "en": "Check how many you have."},
    "bag.sale.shiny_charm": {"ko": "판매하면 이로치 확률이 내려갑니다.", "en": "Selling lowers your shiny chance."},
    "bag.sale.soothe_bell": {"ko": "판매하면 선물 주기가 길어집니다.", "en": "Selling extends the time between gifts."},
    "bag.sale.sold": {"ko": "{item} {quantity}개 판매 · 상점 포인트 +{points}",
                      "en": "Sold {quantity} × {item} · +{points} shop points"},
    "incense.on": {"ko": "향로 켜기", "en": "Turn incense on"},
    "incense.off": {"ko": "향로 끄기", "en": "Turn incense off"},
    "incense.running": {"ko": "사용 중 · {left} 남음", "en": "Active · {left} left"},
    "incense.paused": {"ko": "일시 정지 · {left} 남음", "en": "Paused · {left} left"},
    "incense.empty": {"ko": "남은 향로 시간 없음", "en": "No incense time left"},
    "incense.disguise_found": {"ko": "메타몽을 찾았습니다! 상점 포인트 +{points}",
                              "en": "You found Ditto! +{points} shop points."},
    "bag.charms":       {"ko": "이로치 부적 {n}개 · 이로치 확률 {chance}%",
                         "en": "Shiny Charms {n} · shiny chance {chance}%"},
    "bag.soothe_bell": {"ko": "평온의 방울 {n}개 · 선물 주기 {low}~{high}",
                        "en": "Soothe Bells {n} · gifts every {low}–{high}"},
    "duration.minutes": {"ko": "{minutes}분", "en": "{minutes}m"},
    "duration.minutes_seconds": {"ko": "{minutes}분 {seconds}초", "en": "{minutes}m {seconds}s"},
    "duration.seconds": {"ko": "{seconds}초", "en": "{seconds}s"},

    # --- shop ---
    "shop.buy":         {"ko": "구매",        "en": "Buy"},
    "shop.egg_confirm.title": {"ko": "알 구매 확인", "en": "Confirm egg purchase"},
    "shop.egg_confirm.warning": {
        "ko": "새 알을 구매하면 현재 알이나 키우는 친구가 교체됩니다.\n\n"
              "졸업 전에 교체한 친구는 졸업하지 않은 상태로 남고, 앞으로 알에서 다시 나올 수 있습니다. "
              "졸업할 때까지 향로 방문이나 탐험대 파견처럼 졸업 기록이 필요한 콘텐츠에서 사용이 제한될 수 있습니다.",
        "en": "Buying a new egg replaces your current egg or companion.\n\n"
              "A companion replaced before graduation is not marked as graduated and may hatch again. "
              "Until it graduates, it may be unavailable for features that require graduation, such as incense visits or expeditions.",
    },
    "shop.egg_confirm.cancel": {"ko": "취소", "en": "Cancel"},
    "item.rare_candy":       {"ko": "이상한 사탕", "en": "Rare Candy"},
    "item.rare_candy.office.desc": {"ko": "포켓몬의 성장도를 20 올립니다.",
                                    "en": "Adds 20 growth points to your Pokemon."},
    "item.mint":             {"ko": "민트",       "en": "Mint"},
    "item.mint.desc":        {"ko": "포켓몬의 성격을 다시 굴립니다.",
                              "en": "Re-roll your Pokemon's nature."},
    "item.incense": {"ko": "향로", "en": "Incense"},
    "item.incense.desc": {"ko": "포획된 포켓몬들을 불러옵니다", "en": "Calls previously caught Pokemon"},
    "item.incense.bag.desc": {
        "ko": "포획 기록에 있는 포켓몬을 불러옵니다. 사용 시 10분 추가\n방문객은 가끔 선물을 가져옵니다. 메타몽도 변장해 나타날 수 있습니다.",
        "en": "Calls companions from the growth log. Adds 10 minutes per use.\nVisitors sometimes bring gifts. Ditto can appear in disguise.",
    },
    "item.shiny_charm":      {"ko": "이로치 부적", "en": "Shiny Charm"},
    "item.shiny_charm.desc": {"ko": "이로치 확률이 영구히 올라갑니다.",
                              "en": "Permanently better shiny odds."},
    "item.soothe_bell": {"ko": "평온의 방울", "en": "Soothe Bell"},
    "item.soothe_bell.desc": {"ko": "포켓몬이 선물을 더 자주 가져오게 됩니다",
                              "en": "Your Pokemon brings gifts more often."},
    "item.egg_plain":        {"ko": "포켓몬 알",   "en": "Pokemon Egg"},
    "item.egg_plain.desc":   {"ko": "지금 파트너를 떠나보내고 새로 시작합니다.",
                              "en": "Send off your companion, start again."},
    "item.egg_uncommon":     {"ko": "고급 알",     "en": "Uncommon Egg"},
    "item.egg_uncommon.desc":{"ko": "'조금 귀함' 이상 확정.",
                              "en": "Guaranteed Uncommon or better."},
    "item.egg_rare":         {"ko": "희귀한 알",   "en": "Rare Egg"},
    "item.egg_rare.desc":    {"ko": "'귀함' 이상 확정.",
                              "en": "Guaranteed Rare or better."},

    # --- events ---
    "ev.hatched":       {"ko": "알에서 {name}이(가) 태어났습니다! ({rarity}, {nature}){shiny}",
                         "en": "The egg hatched into {name} ({rarity}, {nature}){shiny}"},
    "ev.shiny_suffix":  {"ko": "  ✨이로치!",  "en": " SHINY!"},
    "ev.evolved":       {"ko": "{before}이(가) {after}(으)로 진화했습니다!",
                         "en": "{before} evolved into {after}!"},
    "ev.graduated":     {"ko": "{name}이(가) 도감에 등록되었습니다! 새 알이 도착했습니다.",
                         "en": "{name} graduated to the Pokedex! A new egg arrived."},
    "ev.collection_complete": {"ko": "모든 일반·이로치 포켓몬의 육성을 마쳤습니다!",
                                 "en": "Every normal and shiny Pokemon has graduated!"},
    "ev.egg_pool_complete": {"ko": "이 알에서 나오는 포켓몬은 모두 졸업했습니다.",
                              "en": "Every Pokemon available from this egg has graduated."},
    "ev.egg_companion_changed": {"ko": "현재 포켓몬이 바뀌었습니다. 구매하려면 다시 확인해 주세요.",
                                  "en": "Your companion changed. Review the purchase again to continue."},
    "save.retry": {"ko": "저장하지 못했습니다. 잠시 후 다시 시도해 주세요.",
                    "en": "Could not save. Please try again shortly."},
    "ev.candy_need":    {"ko": "이상한 사탕은 부화한 포켓몬에게만 쓸 수 있습니다.",
                         "en": "Rare Candy needs a hatched Pokemon."},
    "ev.candy_used.office": {"ko": "이상한 사탕 사용 — 성장도 +{points}!",
                             "en": "Rare Candy used — growth +{points}!"},
    "ev.mint_need":     {"ko": "민트는 부화한 포켓몬에게만 쓸 수 있습니다.",
                         "en": "A Mint needs a hatched Pokemon."},
    "ev.mint_used":     {"ko": "성격 변경: {old} → {new}",
                         "en": "Nature changed: {old} -> {new}"},
    "ev.incense_used": {"ko": "향로 시간이 10분 늘었습니다.", "en": "Added 10 minutes of incense."},
    "ev.unknown_item":  {"ko": "알 수 없는 아이템입니다.", "en": "Unknown item."},
    "ev.too_poor":      {"ko": "포인트가 아직 부족합니다.",   "en": "Not enough points yet."},
    "ev.bought":        {"ko": "{item}을(를) 구매했습니다.", "en": "Bought a {item}."},
    "ev.charm_bought":  {"ko": "이로치 부적 획득 — 이로치 확률 {chance}%",
                         "en": "Shiny Charm acquired — shiny chance {chance}%"},
    "ev.charm_limit": {"ko": "이로치 부적은 최대 {maximum}개까지 보유할 수 있습니다.",
                       "en": "You can hold up to {maximum} Shiny Charms."},
    "ev.bell_limit": {"ko": "평온의 방울은 최대 {maximum}개까지 보유할 수 있습니다.",
                       "en": "You can hold up to {maximum} Soothe Bells."},
    "ev.bell_bought": {"ko": "평온의 방울을 구매했습니다. 포켓몬이 선물을 더 자주 가져오게 됩니다",
                        "en": "Soothe Bell purchased. Gifts will arrive more often!"},
    "ev.egg_bought":    {"ko": "{item} 획득. 파트너를 떠나보냈습니다.",
                         "en": "{item} received. Your companion was sent off."},

    # --- settings ---
    "set.petsize":      {"ko": "데스크톱 펫 크기 (48–192 px)",
                         "en": "Floating pet size (48-192 px)"},
    "set.petsize.hint": {"ko": "가로·세로 중 긴 쪽을 기준으로 크기가 적용됩니다.",
                          "en": "Size applies to the longer side while preserving proportions."},
    "set.incense_crowd": {"ko": "향로 방문 빈도", "en": "Incense visit frequency"},
    "set.incense_crowd.few": {"ko": "적게", "en": "Few"},
    "set.incense_crowd.normal": {"ko": "보통", "en": "Normal"},
    "set.incense_crowd.many": {"ko": "많이", "en": "Many"},
    "set.incense_crowd.swarm": {"ko": "우르르", "en": "Swarm"},
    "set.pet":          {"ko": "데스크톱 펫 띄우기", "en": "Show floating desktop pet"},
    "set.startup":      {"ko": "Windows 로그인 시 자동 시작", "en": "Start automatically when I sign in to Windows"},
    "set.startup_failed": {"ko": "Windows 자동 시작을 적용하지 못했습니다. 설치 경로와 시작 앱 설정을 확인해 주세요.",
                           "en": "Could not apply Windows startup. Check the app's location and Windows startup settings."},
    "set.work_timer": {"ko": "근무 카운트다운", "en": "Work countdown"},
    "set.work_start_time": {"ko": "출근 시간", "en": "Start of work"},
    "set.lunch_time": {"ko": "식사 시작", "en": "Lunch starts"},
    "set.work_resume_time": {"ko": "다음 근무 시작", "en": "Work resumes"},
    "set.work_end_time": {"ko": "퇴근 시간", "en": "End of work"},
    "set.work_time_invalid": {"ko": "{field}을(를) 24시간제 HH:MM으로 입력해 주세요.",
                              "en": "Enter a 24-hour HH:MM time for {field}."},
    "set.work_time_order": {"ko": "출근, 식사 시작, 다음 근무 시작, 퇴근 순서로 시각을 입력해 주세요.",
                             "en": "Set the times in order of work start, lunch, work resuming, and work end."},
    "updates.checking": {"ko": "버전 확인 중", "en": "Checking for updates"},
    "patch_notes.title": {"ko": "패치 노트", "en": "Patch notes"},
    "patch_notes.empty": {"ko": "이 버전의 패치 노트가 없습니다.", "en": "There are no patch notes for this version."},
    "updates.unavailable": {"ko": "버전 확인을 마치지 못했습니다", "en": "Could not check for updates"},
    "updates.current": {"ko": "최신 버전입니다", "en": "Up to date"},
    "updates.available": {"ko": "새 버전 {version}을 받을 수 있습니다.", "en": "Version {version} is available."},
    "updates.installing": {"ko": "{version} 업데이트 준비 중", "en": "Preparing update {version}"},
    "updates.install_failed": {"ko": "자동 업데이트에 실패했습니다.", "en": "Automatic update failed."},
    "updates.download": {"ko": "다운로드", "en": "Download"},
    "work_timer.lunch": {"ko": "식사까지 {time}", "en": "Lunch in {time}"},
    "work_timer.resume": {"ko": "다음 근무까지 {time}", "en": "Work resumes in {time}"},
    "work_timer.end": {"ko": "퇴근까지 {time}", "en": "Finish in {time}"},
    "work_timer.finished": {"ko": "퇴근!", "en": "Workday over!"},
    "set.language":     {"ko": "언어",          "en": "Language"},
    "set.datadir":      {"ko": "세이브 및 이미지 캐시 폴더",
                         "en": "Save and sprite cache folder"},
    "set.save":         {"ko": "저장",          "en": "Save"},
    "set.saved":        {"ko": "저장했습니다.",  "en": "Saved."},
    "set.numbers":      {"ko": "숫자만 입력해 주세요.", "en": "Numbers only, please."},

    # --- tray ---
    "pet.unpin":        {"ko": "고정 해제",   "en": "Unpin"},
    "pet.hide":         {"ko": "펫 숨기기",   "en": "Hide pet"},
    "tray.open":        {"ko": "PokeOfficeBar 열기", "en": "Open PokeOfficeBar"},
    "tray.refresh":     {"ko": "지금 새로고침",   "en": "Refresh now"},
    "tray.pet":         {"ko": "데스크톱 펫",     "en": "Floating pet"},
    "tray.roam":        {"ko": "화면 돌아다니기", "en": "Roam around the screen"},
    "tray.roam.off":    {"ko": "끔", "en": "Off"},
    "tray.roam.screen": {"ko": "화면 전체", "en": "Entire screen"},
    "tray.roam.taskbar":{"ko": "작업 표시줄 위", "en": "Above the taskbar"},
    "tray.quit":        {"ko": "종료",           "en": "Quit"},
    "err.save":         {"ko": "세이브 파일을 읽을 수 없습니다. 진행 상황을 덮어쓰지 않기 위해 "
                               "중단했습니다. save.json을 확인하세요: {err}",
                         "en": "Could not read the save file. Stopped rather than "
                               "overwrite your progress. Check save.json: {err}"},
    "err.refresh":      {"ko": "데이터 불러오기 실패: {err}", "en": "Could not load app data: {err}"},
    "tray.error":       {"ko": "PokeOfficeBar — {err}", "en": "PokeOfficeBar — {err}"},
}
