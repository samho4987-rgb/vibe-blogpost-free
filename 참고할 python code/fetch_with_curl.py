import asyncio
import json
import argparse
import re
import os
import sys
import random
from pathlib import Path

# Windows 콘솔 UTF-8 출력 강제 설정
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# 경로 설정
SCRIPTS_DIR = Path(__file__).parent
BASE_DIR = SCRIPTS_DIR.parent
OUTPUT_DIR = BASE_DIR / "output"
CONFIG_DIR = BASE_DIR / "config"
USER_DATA_DIR = str(BASE_DIR / "playwright_user_data")


def _load_settings():
    """settings.yaml에서 네이버 계정 정보 로드"""
    try:
        import yaml
        settings_path = CONFIG_DIR / "settings.yaml"
        with open(settings_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception:
        return {}


def parse_html_data(html, article_no):
    """렌더링된 HTML을 BeautifulSoup으로 파싱하여 매물 정보 추출"""
    soup = BeautifulSoup(html, 'html.parser')

    info = {
        "articleNo": article_no,
        "features": []
    }

    # 1. 가격 정보 추출
    # <span class="ArticleSummary-module__info-price__...">매매 24억 5,000</span>
    price_tag = soup.find(
        lambda tag: tag.name == "span"
        and tag.get("class")
        and any("info-price" in c for c in tag.get("class"))
    )
    if price_tag:
        full_price = price_tag.get_text(strip=True)
        if " " in full_price:
            info["trade_type"], info["price"] = full_price.split(" ", 1)
        else:
            info["price"] = full_price
            info["trade_type"] = "매매"

    # 2. 상세 정보 (면적, 층, 향)
    details = soup.find_all(
        lambda tag: tag.name == "li"
        and tag.get("class")
        and any("item-detail" in c for c in tag.get("class"))
    )
    for detail in details:
        text = detail.get_text(strip=True)
        if "㎡" in text:
            info["area_display"] = text
            match = re.search(r"(\d+(\.\d+)?)㎡", text)
            if match:
                info["area"] = match.group(1)
        elif "층" in text:
            info["floor"] = text
        elif "향" in text:
            info["direction"] = text

    # 3. 제목 (건물명)
    title_tag = soup.find("meta", property="og:title")
    if title_tag:
        info["title"] = title_tag["content"]

    # 4. 대표 이미지
    image_tag = soup.find("meta", property="og:image")
    if image_tag:
        info["image_url"] = image_tag["content"]

    # 5. 특징 태그 (ArticleSummary description)
    summary_descs = soup.find_all(
        lambda tag: tag.get("class")
        and any("ArticleSummary" in c and "description" in c for c in tag.get("class"))
    )
    for desc in summary_descs:
        info["features"].append(desc.get_text(strip=True))

    # 6. 상세 설명 (ArticleDetailInfo description)
    detail_descs = soup.find_all(
        lambda tag: tag.get("class")
        and any("ArticleDetailInfo" in c and "description" in c for c in tag.get("class"))
    )
    if detail_descs:
        full_text = []
        for d in detail_descs:
            full_text.append(d.get_text(separator="\n", strip=True))
        info["detail_description"] = "\n\n".join(full_text)

    # 7. 메타 설명 (og:description)
    desc_tag = soup.find("meta", property="og:description")
    if desc_tag:
        info["description"] = desc_tag["content"]

    # 8. DataList 항목 (방수/욕실수, 향, 입주가능일, 현관구조, 난방, 주차, 건설사, 세대수, 사용승인, 용도, 주소, 관리비, 중개사 정보)
    items = soup.find_all(
        lambda tag: tag.get("class")
        and any("DataList" in c and "item" in c for c in tag.get("class"))
    )
    for item in items:
        term_tag = item.find(
            lambda tag: tag.get("class") and any("term" in c for c in tag.get("class"))
        )
        def_tag = item.find(
            lambda tag: tag.get("class") and any("definition" in c for c in tag.get("class"))
        )

        if not (term_tag and def_tag):
            continue

        term = term_tag.get_text(strip=True)
        definition = def_tag.get_text(" ", strip=True)

        if "방/욕실수" in term or "방수/욕실수" in term:
            info["room_bath_count"] = definition
        elif "향" in term and "direction" not in info:
            info["direction"] = definition.replace("(거실 기준)", "").strip()
        elif "입주가능일" in term:
            info["available_date"] = definition
        elif "현관구조" in term:
            info["entrance_type"] = definition
        elif "난방" in term:
            info["heating"] = definition
        elif "주차" in term:
            if "(" in definition:
                main_p, sub_p = definition.split("(", 1)
                info["parking"] = f"{main_p.strip()} ({sub_p.strip()}"
            else:
                info["parking"] = definition
        elif "건설사" in term:
            info["builder"] = definition
        elif "세대수" in term:
            info["total_units"] = definition
        elif "사용승인" in term:
            info["approval_date"] = definition.split("(")[0].strip()
        elif "건축물" in term and "용도" in term:
            info["building_use"] = definition
        elif "소재지" in term or (
            "주소" in term
            and "agent" not in "".join(item.get("class", []))
        ):
            if any(x in definition for x in ["서울", "경기", "인천", "도 ", "시 ", "구 ", "군 "]):
                info["complex_address"] = definition
        elif "관리비" in term:
            info["maintenance_info"] = [
                s for s in def_tag.stripped_strings if "상세보기" not in s
            ]
        elif "위치" in term:
            info["realtor_address"] = definition
        elif "등록번호" in term:
            info["realtor_reg_num"] = definition
        elif "전화" in term:
            phones = [
                a.get_text(strip=True)
                for a in def_tag.find_all("a")
                if "tel:" in a.get("href", "")
            ]
            if phones:
                info["realtor_phone"] = phones[0]
                if len(phones) > 1:
                    info["realtor_mobile"] = phones[1]

    # 9. 단지 주소 강제 탐색 (위에서 못 찾은 경우 추가 시도)
    def is_real_address(text):
        if not text or len(text) < 5:
            return False
        return any(x in text for x in ["서울", "경기", "인천", "부산", "대구", "광주", "대전", "울산", "세종", "도", "시", "구", "군", "동", "로", "길"])

    if "complex_address" not in info or not is_real_address(info.get("complex_address", "")):
        # 방법 A: ArticleComplexInfo area-data 클래스 탐색
        complex_addr_tags = soup.find_all(
            lambda tag: tag.get("class")
            and any("ArticleComplexInfo" in c and "area-data" in c for c in tag.get("class"))
        )
        for tag in complex_addr_tags:
            addr_candidate = tag.get_text(strip=True)
            addr_candidate = addr_candidate.replace("지도보기", "").replace("상세보기", "").strip()
            if is_real_address(addr_candidate):
                info["complex_address"] = addr_candidate
                break

        # 방법 B: '소재지' 텍스트 근처 탐색
        if "complex_address" not in info or not is_real_address(info.get("complex_address", "")):
            loc_tags = soup.find_all(
                lambda tag: "소재지" in tag.get_text() and len(tag.get_text()) < 10
            )
            for lt in loc_tags:
                candidate = lt.find_next(string=True)
                if candidate and is_real_address(candidate):
                    info["complex_address"] = candidate.strip()
                    break

        # 방법 C: 정규식으로 주소 패턴 탐색
        if "complex_address" not in info or not is_real_address(info.get("complex_address", "")):
            addr_pattern = re.compile(
                r"(서울|경기|인천|부산|대구|광주|대전|울산|세종)\s+[가-힣]+\s+[가-힣\d\s-]+(동|리|가|길|로)\s+\d+([-]\d+)?"
            )
            all_text = soup.get_text(" ", strip=True)
            for m in addr_pattern.finditer(all_text):
                addr = m.group().strip()
                if "realtor_address" in info and info["realtor_address"]:
                    if addr[:10] in info["realtor_address"]:
                        continue
                info["complex_address"] = addr
                break

    # 10. 중개사 이름 및 중개소명
    realtor_name_tag = soup.find(
        lambda tag: tag.get("class")
        and any("broker-name" in c for c in tag.get("class"))
    )
    if realtor_name_tag:
        info["realtor_ceo"] = realtor_name_tag.get_text(strip=True)
        parent_text = realtor_name_tag.find_parent().get_text(" ", strip=True)
        info["realtor_name"] = parent_text.replace(info["realtor_ceo"], "").strip()

    # 11. 전화번호 폴백 추출 (DataList에 tel: 링크가 없는 경우 detail_description에서 추출)
    if "realtor_phone" not in info and "detail_description" in info:
        phone_pattern = re.compile(r"0\d{1,2}-\d{3,4}-\d{4}")
        phones_found = phone_pattern.findall(info["detail_description"])
        unique_phones = list(dict.fromkeys(phones_found))  # 순서 유지 중복 제거
        if len(unique_phones) >= 1:
            info["realtor_phone"] = unique_phones[0]
        if len(unique_phones) >= 2:
            info["realtor_mobile"] = unique_phones[1]

    return info


async def _do_naver_login(page, user_id: str, user_pw: str):
    """네이버 로그인 페이지에서 자동 로그인 처리"""
    print("  로그인 페이지 대기 중...")
    try:
        await page.wait_for_selector("#id", timeout=10000)
    except:
        print("  [ERROR] 로그인 입력창을 찾을 수 없습니다.")
        return

    print("  📝 자바스크립트 주입(insertText) 방식으로 로그인 시도...")
    
    # ID 입력
    await page.focus("#id")
    await asyncio.sleep(0.5)
    await page.evaluate(f"document.execCommand('insertText', false, '{user_id}');")
    await asyncio.sleep(random.uniform(0.5, 1.0))
    
    # PW 입력
    await page.focus("#pw")
    await asyncio.sleep(0.5)
    await page.evaluate(f"document.execCommand('insertText', false, '{user_pw}');")
    await asyncio.sleep(random.uniform(0.5, 1.0))
    
    # 로그인 버튼 클릭
    await page.click(".btn_login")
    print("  🔐 로그인 버튼 클릭 완료. 결과 대기 중...")

    try:
        # 로그인 성공 후 이동 감지
        await page.wait_for_url("**/www.naver.com/**", timeout=20000)
        print("  ✅ 로그인 성공")
    except Exception:
        print("  ⚠️ 로그인 응답 대기 타임아웃 (2차 인증/캡차 필요 시 수집이 제한될 수 있습니다)")


async def fetch_property_page(article_no: str) -> str:
    """
    Playwright 영구 컨텍스트로 매물 상세 페이지 HTML 가져오기.
    - playwright_user_data 디렉토리에 이전 세션 쿠키가 저장되어 자동 재사용
    - 세션 만료 시 settings.yaml 계정으로 자동 로그인
    - 매물 데이터가 렌더링될 때까지 대기 후 HTML 반환
    """
    url = f"https://fin.land.naver.com/articles/{article_no}"
    settings = _load_settings()
    naver_id = settings.get('naver', {}).get('user_id', '')
    naver_pw = settings.get('naver', {}).get('user_pw', '')

    print(f"[fetch] 매물 페이지 로딩 중... ({url})")

    async with async_playwright() as p:
        # 영구 컨텍스트: 로그인 쿠키를 파일에 저장하여 재사용
        context = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
            ],
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1280, "height": 900},
        )

        # 자동화 감지 우회
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['ko-KR', 'ko', 'en-US', 'en'] });
        """)

        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)

            # 로그인 리다이렉트 감지 및 처리
            current_url = page.url
            if "nid.naver.com" in current_url or "/login" in current_url:
                if naver_id and naver_pw:
                    print("[INFO] 세션 만료 감지 - 자동 로그인 시도...")
                    await _do_naver_login(page, naver_id, naver_pw)
                    print("[INFO] 매물 페이지로 재이동...")
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(1)
                else:
                    print("[ERROR] 로그인이 필요하지만 config/settings.yaml에 계정 정보가 없습니다.")
                    return ""

            # 매물 데이터 렌더링 대기 (React/Next.js CSR 처리)
            try:
                await page.wait_for_selector(
                    "[class*='info-price']",
                    timeout=15000
                )
                print("[OK] 매물 데이터 렌더링 완료")
            except Exception:
                print("[WARNING] 가격 정보 요소 대기 타임아웃 - 현재 HTML로 파싱 시도")
                await asyncio.sleep(3)

            html = await page.content()
            return html

        except Exception as e:
            print(f"[ERROR] 페이지 로딩 오류: {e}")
            return ""
        finally:
            await context.close()


def main():
    parser = argparse.ArgumentParser(
        description="네이버 부동산 매물 정보 수집 (Playwright 기반)"
    )
    parser.add_argument("articleNo", type=str, help="매물 번호")
    parser.add_argument(
        "--output", type=str,
        help="결과 저장 경로 (기본: output/property_{articleNo}.json)"
    )
    args = parser.parse_args()

    print(f"[START] 매물 번호 {args.articleNo} 정보 수집 시작...")

    html = asyncio.run(fetch_property_page(args.articleNo))

    if not html:
        print("[ERROR] HTML 가져오기 실패")
        sys.exit(1)

    # 디버그용 HTML 저장
    debug_path = BASE_DIR / "debug_raw.html"
    with open(debug_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[SAVE] 디버그 HTML 저장: {debug_path}")

    # HTML 파싱
    data = parse_html_data(html, args.articleNo)

    # 결과 출력
    print("\n=== 수집된 데이터 ===")
    print(json.dumps(data, ensure_ascii=False, indent=2))

    # 결과 저장
    output_path = args.output
    if not output_path:
        OUTPUT_DIR.mkdir(exist_ok=True)
        output_path = str(OUTPUT_DIR / f"property_{args.articleNo}.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 수집 결과 요약
    collected = [k for k, v in data.items() if v and v != [] and v != "-"]
    print(f"\n[DONE] 저장 완료: {output_path}")
    print(f"수집된 필드 ({len(collected)}개): {', '.join(collected)}")


if __name__ == "__main__":
    main()
