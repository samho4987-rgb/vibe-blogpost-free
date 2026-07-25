import os
import sys
import yaml
import asyncio
import random
import re
import win32clipboard
from playwright.async_api import async_playwright

# --- 경로 설정 수정됨 ---
# 현재 스크립트의 위치 (scripts 폴더)
CURRENT_DIR = os.path.abspath(os.path.dirname(__file__))
# 프로젝트 루트 (scripts의 부모 폴더)
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
# Config 폴더 위치 (프로젝트 루트/config)
CONFIG_BASE = os.path.join(PROJECT_ROOT, "config")
# 영구 프로필 저장 경로
PROFILE_DIR = os.path.join(PROJECT_ROOT, ".naver_profile")

def load_yaml(file_name):
    path = os.path.join(CONFIG_BASE, file_name)
    if not os.path.exists(path):
        # 혹시 몰라 scripts/config 도 확인 (유연성 확보)
        fallback_path = os.path.join(CURRENT_DIR, "config", file_name)
        if os.path.exists(fallback_path):
            return load_yaml_from_path(fallback_path)
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다.\n검색 경로 1: {path}\n검색 경로 2: {fallback_path}")
    return load_yaml_from_path(path)

def load_yaml_from_path(path):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

print(f"설정 파일 경로 확인: {CONFIG_BASE}")

try:
    selectors = load_yaml("blog_selectors.yaml")
    settings = load_yaml("settings.yaml")
except Exception as e:
    print(f"❌ 설정 로드 실패: {e}")
    sys.exit(1)

NAVER_ID = settings['naver'].get('user_id', '')
NAVER_PW = settings['naver'].get('user_pw', '')

def copy_to_clipboard(text: str):
    """일반 텍스트를 클립보드에 복사합니다 (로그인용)."""
    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    win32clipboard.CloseClipboard()

def copy_html_to_clipboard(html_content: str):
    """HTML 형식으로 클립보드에 복사합니다 (본문 표 삽입용)."""
    CF_HTML = win32clipboard.RegisterClipboardFormat("HTML Format")
    
    html_template = f"""Version:0.9
StartHTML:00000097
EndHTML:{97 + len(html_content) + 36:08d}
StartFragment:00000133
EndFragment:{133 + len(html_content):08d}
<html><body>
<!--StartFragment-->{html_content}<!--EndFragment-->
</body></html>"""
    
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(CF_HTML, html_template.encode('utf-8'))
    finally:
        win32clipboard.CloseClipboard()


def generate_property_tables(property_data: dict) -> dict:
    """부동산 매물 정보를 개별 HTML 표 딕셔너리로 변환합니다."""
    
    detail = property_data.get('detail', {})
    complex_info = property_data.get('complex', {})
    summary = property_data.get('summary', {})
    realtor = property_data.get('realtor', {})
    
    if not detail: detail = {}
    if not complex_info: complex_info = {}
    if not summary: summary = {}
    if not realtor: realtor = {}

    STYLE_TABLE = "border-collapse: collapse; width: 100%; max-width: 600px; margin: 10px 0; font-family: 'Malgun Gothic', sans-serif; border: 1px solid #dfe4ea;"
    STYLE_HEADER = "padding: 15px; text-align: center; background-color: #2c3e50; color: #ffffff; font-size: 16px; font-weight: bold; border: 1px solid #2c3e50;"
    STYLE_LABEL = "background-color: #eff3f6; border: 1px solid #dfe4ea; padding: 12px 15px; width: 30%; color: #2c3e50; font-weight: bold;"
    STYLE_VALUE = "border: 1px solid #dfe4ea; padding: 12px 15px; color: #333; line-height: 1.5;"

    summary_html = f'''
<table style="{STYLE_TABLE}">
    <thead>
        <tr>
            <th colspan="2" style="{STYLE_HEADER}">매물정보</th>
        </tr>
    </thead>
    <tbody>
        <tr><td style="{STYLE_LABEL}">매물명</td><td style="{STYLE_VALUE}">{summary.get('building_name', '-')}</td></tr>
        <tr><td style="{STYLE_LABEL}">면적(공급/전용)</td><td style="{STYLE_VALUE}">{summary.get('supply_area', '-')} / {summary.get('private_area', '-')}</td></tr>
        <tr><td style="{STYLE_LABEL}">가격</td><td style="{STYLE_VALUE}"><strong style="color: #d32f2f; font-size: 1.1em;">{summary.get('price', '-')}</strong></td></tr>
        <tr><td style="{STYLE_LABEL}">해당층/총층</td><td style="{STYLE_VALUE}">{summary.get('floor_info', '-')}</td></tr>
        <tr><td style="{STYLE_LABEL}">입주가능일</td><td style="{STYLE_VALUE}">{summary.get('available_date', '즉시입주 협의가능')}</td></tr>
        <tr><td style="{STYLE_LABEL}">방수/욕실수</td><td style="{STYLE_VALUE}">{summary.get('room_bath_count', '-')}</td></tr>
        <tr><td style="{STYLE_LABEL}">관리비</td><td style="{STYLE_VALUE} line-height: 1.6;">{summary.get('maintenance_fee', '-')}</td></tr>
    </tbody>
</table>
'''

    detail_html = f'''
<table style="{STYLE_TABLE}">
    <thead>
        <tr>
            <th colspan="2" style="{STYLE_HEADER}">매물 세부 정보</th>
        </tr>
    </thead>
    <tbody>
        <tr><td style="{STYLE_LABEL}">해당동</td><td style="{STYLE_VALUE}">{detail.get('building_num', '-')}</td></tr>
        <tr><td style="{STYLE_LABEL}">방향</td><td style="{STYLE_VALUE}">{detail.get('direction', '-')}</td></tr>
        <tr><td style="{STYLE_LABEL}">현관구조</td><td style="{STYLE_VALUE}">{detail.get('entrance_type', '-')}</td></tr>
    </tbody>
</table>
'''

    complex_html = f'''
<table style="{STYLE_TABLE}">
    <thead>
        <tr>
            <th colspan="2" style="{STYLE_HEADER}">단지정보</th>
        </tr>
    </thead>
    <tbody>
        <tr><td style="{STYLE_LABEL}">건축물용도</td><td style="{STYLE_VALUE}">{complex_info.get('building_use', '-')}</td></tr>
        <tr><td style="{STYLE_LABEL}">총세대수</td><td style="{STYLE_VALUE}">{complex_info.get('total_units', '-')}</td></tr>
        <tr><td style="{STYLE_LABEL}">주차대수</td><td style="{STYLE_VALUE}">{complex_info.get('parking', '-')}</td></tr>
        <tr><td style="{STYLE_LABEL}">난방방식</td><td style="{STYLE_VALUE}">{complex_info.get('heating_type', '-')}</td></tr>
        <tr><td style="{STYLE_LABEL}">건설사</td><td style="{STYLE_VALUE}">{complex_info.get('builder', '-')}</td></tr>
        <tr><td style="{STYLE_LABEL}">사용승인</td><td style="{STYLE_VALUE}">{complex_info.get('approval_date', '-')}</td></tr>
        <tr><td style="{STYLE_LABEL}">주소</td><td style="{STYLE_VALUE}">{complex_info.get('address', '-')}</td></tr>
    </tbody>
</table>
'''

    realtor_html = f'''
<table style="{STYLE_TABLE}">
    <thead>
        <tr>
            <th colspan="2" style="{STYLE_HEADER}">{realtor.get('name', '공인중개사 정보')}</th>
        </tr>
    </thead>
    <tbody>
        <tr><td style="{STYLE_LABEL}">대표자</td><td style="{STYLE_VALUE}">{realtor.get('ceo', '-')}</td></tr>
        <tr><td style="{STYLE_LABEL}">개설등록번호</td><td style="{STYLE_VALUE}">{realtor.get('reg_num', '-')}</td></tr>
        <tr><td style="{STYLE_LABEL}">대표번호</td><td style="{STYLE_VALUE}">{realtor.get('phone', '-')}</td></tr>
        <tr><td style="{STYLE_LABEL}">휴대폰번호</td><td style="{STYLE_VALUE}">{realtor.get('mobile', '-')}</td></tr>
        <tr><td style="{STYLE_LABEL}">주소</td><td style="{STYLE_VALUE}">{realtor.get('address', '-')}</td></tr>
    </tbody>
</table>
'''
    
    return {
        'summary': summary_html,
        'detail': detail_html,
        'complex': complex_html,
        'realtor': realtor_html,
        'all': summary_html + detail_html + complex_html + realtor_html
    }


def generate_property_table_html(property_data: dict) -> str:
    """기존 호환성 유지를 위한 함수 (전체 테이블 반환)"""
    tables = generate_property_tables(property_data)
    return tables['all']


async def insert_html_table(page, html_content: str):
    """HTML 표를 클립보드를 통해 에디터에 삽입합니다."""
    copy_html_to_clipboard(html_content)
    await asyncio.sleep(0.5)
    # 붙여넣기 (Ctrl+V)
    await page.keyboard.press("Control+V")
    await asyncio.sleep(1.0)


async def smart_type(page, text: str, delay_range=(0.04, 0.12)):
    """사람처럼 보이게 하기 위해 랜덤 딜레이를 주며 타이핑합니다."""
    if not text: return
    for i, char in enumerate(text):
        await page.keyboard.type(char)
        
        # 기본 타이핑 속도를 사람처럼 약간 늦춤
        delay = random.uniform(*delay_range) 
        
        # 띄어쓰기나 구두점에서는 생각이 지연되는 척 좀 더 길게 쉼
        if char in [' ', ',', '.', '!', '?', '\n']:
            delay += random.uniform(0.1, 0.3)
            
        # 15~25글자마다 한 번씩 숨을 쉬거나 오타를 교정하는 척 정지
        if i > 0 and i % random.randint(15, 25) == 0:
            delay += random.uniform(0.4, 1.2)
            
        await asyncio.sleep(delay)


async def naver_login_and_write(property_data: dict = None, title: str = None, content: str = None):
    """네이버 블로그에 로그인하고 글을 작성합니다."""
    
    # 테스트용 기본 데이터 (직접 실행 시 사용됨)
    if property_data is None:
        property_data = {
            'detail': {
                'title': '테스트 매물: 고덕그라시움',
                'building_num': '141동',
                'direction': '남향',
                'entrance_type': '계단식'
            },
            'complex': {
                'total_buildings': '53개동',
                'total_units': '4932세대',
                'parking': '세대당 1.45대',
                'heating_type': '지역난방',
                'builder': '대우건설 외 컨소시엄',
                'approval_date': '2019.09',
                'address': '서울시 강동구 고덕동'
            }
        }
    
    if title is None:
        title = "[테스트] AI 부동산 블로그 포스팅 자동화"
    
    if content is None:
        content = """안녕하세요.\n이 글은 Python Playwright를 이용한 **블로그 자동 포스팅 테스트**입니다.\n\n아래에 매물 정보 표가 올바르게 삽입되었는지 확인해주세요."""
    
    async with async_playwright() as p:
        print("--- 1. 네이버 로그인 시도 (영구 프로필 세션 사용) ---")
        
        # 영구 브라우저 프로필을 사용하여 세션 유지 (캡차 최소화)
        context = await p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # 로그인 페이지 접속
        await page.goto(settings['naver']['login_url'])
        await asyncio.sleep(2)
        
        # 이미 로그인된 상태인지 체크 (로그인 페이지에 머물러 있는지 확인)
        if 'nid.naver.com' not in page.url:
            print("✅ 이미 로그인된 상태입니다 (영구 세션 유지).")
        else:
            print("📝 자바스크립트 주입(insertText) 방식으로 보안 우회 로그인 시도...")
            
            # ID 입력 (JS insertText 방식 - OS 클립보드에 의존하지 않음)
            await page.focus("#id")
            await asyncio.sleep(0.5)
            await page.evaluate(f"document.execCommand('insertText', false, '{NAVER_ID}');")
            await asyncio.sleep(random.uniform(0.5, 1.0))
            
            # PW 입력
            await page.focus("#pw")
            await asyncio.sleep(0.5)
            await page.evaluate(f"document.execCommand('insertText', false, '{NAVER_PW}');")
            await asyncio.sleep(random.uniform(0.5, 1.0))
            
            # 로그인 버튼 클릭
            await page.click(".btn_login")
            print("🔐 로그인 버튼 클릭 완료. 결과 대기 중...")

            try:
                # 메인 페이지나 로그인 후 페이지 대기
                await page.wait_for_url("**/www.naver.com/**", timeout=20000)
                print("✅ 로그인 성공!")
            except:
                print("\n" + "="*70)
                print("⚠️ 자동 로그인이 차단되었거나 2차 인증(캡차)이 발생했습니다.")
                print("1. 브라우저 창에서 로그인을 직접 완료해 주세요 (인증번호 입력 등).")
                print("2. 로그인이 보이지 않으면 네이버 홈페이지로 직접 이동해 세션을 잡아주세요.")
                print("3. 완료 후 터미널(콘솔)에서 Enter 키를 치면 다음 단계로 진행합니다.")
                print("="*70 + "\n")
                
                # 비공식 대기 (수동 해결 확인)
                await asyncio.get_event_loop().run_in_executor(None, input, ">>> 로그인 및 인증 완료 후 Enter를 눌러주세요:")
                print("✅ 사용자 확인 완료. 다음 단계로 진행합니다.")

        print("--- 2. 블로그 글쓰기 페이지 이동 ---")
        await page.goto(settings['naver']['blog_write_url'])
        await asyncio.sleep(3)
        
        # 에디터 iframe 로딩 대기
        iframe_selector = f"iframe#{selectors['editor']['iframe'][0]}"
        try:
            await page.wait_for_selector(iframe_selector, timeout=30000)
        except:
            print("❌ 에디터 로딩 실패. 수동 로그인이 안 되었거나 네트워크 장애일 수 있습니다.")
            await context.close()
            return

        frame = page.frame(name=selectors['editor']['iframe'][0])

        print("--- 3. 안내 팝업 및 도움말 처리 ---")
        await asyncio.sleep(2)
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.5)

        popup_selectors = [
            selectors['popup']['close'][0],
            "button.se-popup-button-cancel", 
            "button.se-popup-button-confirm",
            ".se-popup-button-cancel",
            ".se-popup-button-confirm"
        ]
        
        for sel in popup_selectors:
            try:
                btn = frame.locator(sel)
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click(timeout=2000)
                    print(f"✅ 안내 팝업을 셀렉터({sel})로 닫았습니다.")
                    break
            except:
                continue

        try:
            help_close_btn = frame.locator("button.se-help-panel-close-button")
            if await help_close_btn.count() > 0 and await help_close_btn.is_visible():
                await help_close_btn.first.click()
                print("✅ 도움말 창을 닫았습니다.")
        except:
            pass

        await asyncio.sleep(1)
        print("에디터 준비 완료.")

        print("--- 4. 제목 작성 ---")
        title_written = False
        for title_sel in selectors['editor']['title']:
            try:
                t = frame.locator(title_sel).first
                if await t.is_visible():
                    await t.click()
                    await asyncio.sleep(0.5)
                    await smart_type(page, title)
                    title_written = True
                    print("제목 입력 완료")
                    break
            except:
                continue
        
        if not title_written:
            print("⚠️ 제목 입력 실패 (셀렉터 못 찾음)")

        print("--- 5. 본문 작성 ---")
        await page.keyboard.press("Enter")
        await asyncio.sleep(0.3)
        await page.keyboard.press("Enter")
        await asyncio.sleep(0.5)
        print("✅ Enter 키로 본문 영역 이동 완료")

        async def apply_subtitle_format(frame, line_text):
            """소제목 형식 적용 (## 텍스트)"""
            clean_text = line_text.lstrip('#').strip()
            for sel in selectors['toolbar']['text_format']['dropdown']:
                try:
                    btn = frame.locator(sel)
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(0.3)
                        break
                except: continue
            for sel in selectors['toolbar']['text_format']['subtitle']:
                try:
                    btn = frame.locator(sel)
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(0.2)
                        break
                except: continue
            await smart_type(page, clean_text)
            await page.keyboard.press("Enter")
            for sel in selectors['toolbar']['text_format']['dropdown']:
                try:
                    btn = frame.locator(sel)
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(0.3)
                        break
                except: continue
            for sel in selectors['toolbar']['text_format']['body']:
                try:
                    btn = frame.locator(sel)
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(0.2)
                        break
                except: continue

        async def apply_bold_inline(page, line_text):
            """인라인 굵게 처리 (**텍스트**)"""
            import re
            bold_pattern = re.compile(r'\*\*(.+?)\*\*')
            parts = bold_pattern.split(line_text)
            is_bold = False
            for part in parts:
                if part:
                    if is_bold:
                        await page.keyboard.press("Control+B")
                        await asyncio.sleep(0.1)
                        await smart_type(page, part)
                        await page.keyboard.press("Control+B")
                        await asyncio.sleep(0.1)
                    else:
                        await smart_type(page, part)
                is_bold = not is_bold

        async def insert_divider_line(frame):
            """구분선(line1 - 굵은 실선) 삽입"""
            for sel in selectors['insert']['divider']['dropdown']:
                try:
                    btn = frame.locator(sel)
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(0.3)
                        break
                except: continue
            for sel in selectors['insert']['divider']['styles']['line1']:
                try:
                    btn = frame.locator(sel)
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(0.2)
                        break
                except: continue

        if content:
            import re
            html_pattern = re.compile(r'<table.*?</table>', re.DOTALL)
            parts = html_pattern.split(content)
            html_tables = html_pattern.findall(content)
            
            table_idx = 0
            last_was_empty = False
            
        async def upload_thumbnail(page, article_no):
            """썸네일 이미지 업로드"""
            import os
            
            # 예상 경로: output/thumbnails/thumbnail_{article_no}.png
            # (확장자는 png 또는 jpg일 수 있으므로 확인)
            base_path = os.path.join(PROJECT_ROOT, "output", "thumbnails")
            filename = f"thumbnail_{article_no}"
            
            image_path = None
            for ext in ['.png', '.jpg', '.jpeg', '.webp']:
                path = os.path.join(base_path, filename + ext)
                if os.path.exists(path):
                    image_path = path
                    break
            
            if not image_path:
                print(f"⚠️ 썸네일 이미지를 찾을 수 없습니다: {os.path.join(base_path, filename + '.*')}")
                return

            print(f"🖼️ 썸네일 업로드 시도: {image_path}")
            
            # 파일 업로드 (file chooser 방식)
            try:
                # 1. 사진 버튼 클릭 트리거
                file_input_sels = selectors['insert']['image']['file_input']
                btn_sels = selectors['insert']['image']['button']
                
                # 파일 인풋이 숨겨져 있을 수 있으므로, 버튼을 눌러서 찾거나 set_input_files 사용
                # 네이버 에디터는 보통 숨겨진 input[type='file']이 있음
                
                # 방법 A: set_input_files를 사용하여 숨겨진 input에 직접 업로드
                # 먼저 frame 내부인지 page 내부인지 확인 필요 (보통 page 레벨에 숨겨져 있거나 frame 내부에 있음)
                
                # frame 내부 input 확인
                input_found = False
                for sel in file_input_sels:
                    if await frame.locator(sel).count() > 0:
                        await frame.locator(sel).set_input_files(image_path)
                        input_found = True
                        print("✅ 이미지 파일 설정 완료 (Frame)")
                        break
                
                if not input_found:
                    # Page 내부 input 확인
                    for sel in file_input_sels:
                        if await page.locator(sel).count() > 0:
                            await page.locator(sel).set_input_files(image_path)
                            input_found = True
                            print("✅ 이미지 파일 설정 완료 (Page)")
                            break
                            
                if not input_found:
                    # 버튼 클릭 후 file chooser 대기 방식
                    async with page.expect_file_chooser() as fc_info:
                        clicked = False
                        for sel in btn_sels:
                            try:
                                btn = frame.locator(sel)
                                if await btn.count() > 0 and await btn.is_visible():
                                    await btn.click()
                                    clicked = True
                                    break
                            except: continue
                        
                        if not clicked:
                            # 툴바가 page에 있을 수도 있음
                             for sel in btn_sels:
                                try:
                                    btn = page.locator(sel)
                                    if await btn.count() > 0 and await btn.is_visible():
                                        await btn.click()
                                        clicked = True
                                        break
                                except: continue
                                
                        if clicked:
                            file_chooser = await fc_info.value
                            await file_chooser.set_files(image_path)
                            print("✅ 파일 선택기(File Chooser)를 통해 이미지 업로드 완료")
                        else:
                            print("❌ 사진 업로드 버튼을 찾을 수 없습니다.")
                            return

                await asyncio.sleep(3) # 업로드 대기
                
            except Exception as e:
                print(f"❌ 이미지 업로드 중 오류 발생: {e}")

        if content:
            import re
            html_pattern = re.compile(r'<table.*?</table>', re.DOTALL)
            parts = html_pattern.split(content)
            html_tables = html_pattern.findall(content)
            
            table_idx = 0
            last_was_empty = False
            
            for i, part in enumerate(parts):
                lines = part.split('\n')
                for j, line in enumerate(lines):
                    stripped = line.strip()
                    
                    if not stripped:
                        if not last_was_empty:
                            await page.keyboard.press("Enter")
                            await asyncio.sleep(0.03)
                        last_was_empty = True
                        continue
                    
                    if stripped == '---':
                        await insert_divider_line(frame)
                        last_was_empty = True
                        continue

                    # [THUMBNAIL_IMAGE] 처리
                    if '[THUMBNAIL_IMAGE]' in stripped:
                        await upload_thumbnail(page, article_no)
                        # 플레이스홀더 라인은 제거하고 다음으로 이동
                        last_was_empty = False 
                        continue
                    
                    last_was_empty = False
                    
                    if stripped.startswith('## '):
                        await apply_subtitle_format(frame, stripped)
                        continue
                    
                    if stripped.startswith('- '):
                        stripped = stripped[2:]
                    
                    if '**' in stripped:
                        await apply_bold_inline(page, stripped)
                    else:
                        await smart_type(page, stripped)
                    
                    if j < len(lines) - 1:
                        await page.keyboard.press("Enter")
                        await asyncio.sleep(0.03)
                
                if table_idx < len(html_tables):
                    await insert_html_table(page, html_tables[table_idx])
                    print(f"HTML 테이블 {table_idx + 1} 삽입 완료")
                    table_idx += 1
            
            await page.keyboard.press("Enter")
            print("본문 작성 완료")

        async def upload_contact_banner(page, frame, phone_number="02-3436-1212"):
            """전화 연결 배너 이미지 업로드 및 링크 추가"""
            banner_path = os.path.join(PROJECT_ROOT, "templates", "전화연결.png")
            
            if not os.path.exists(banner_path):
                print(f"⚠️ 배너 이미지를 찾을 수 없습니다: {banner_path}")
                return
            
            print(f"📞 전화 연결 배너 업로드 시도: {banner_path}")
            
            try:
                file_input_sels = selectors['insert']['image']['file_input']
                btn_sels = selectors['insert']['image']['button']
                
                input_found = False
                for sel in file_input_sels:
                    if await frame.locator(sel).count() > 0:
                        await frame.locator(sel).set_input_files(banner_path)
                        input_found = True
                        print("✅ 배너 이미지 파일 설정 완료 (Frame)")
                        break
                
                if not input_found:
                    for sel in file_input_sels:
                        if await page.locator(sel).count() > 0:
                            await page.locator(sel).set_input_files(banner_path)
                            input_found = True
                            print("✅ 배너 이미지 파일 설정 완료 (Page)")
                            break
                            
                if not input_found:
                    async with page.expect_file_chooser() as fc_info:
                        clicked = False
                        for sel in btn_sels:
                            try:
                                btn = frame.locator(sel)
                                if await btn.count() > 0 and await btn.is_visible():
                                    await btn.click()
                                    clicked = True
                                    break
                            except: continue
                        
                        if not clicked:
                            for sel in btn_sels:
                                try:
                                    btn = page.locator(sel)
                                    if await btn.count() > 0 and await btn.is_visible():
                                        await btn.click()
                                        clicked = True
                                        break
                                except: continue
                                
                        if clicked:
                            file_chooser = await fc_info.value
                            await file_chooser.set_files(banner_path)
                            print("✅ 파일 선택기를 통해 배너 이미지 업로드 완료")
                        else:
                            print("❌ 사진 업로드 버튼을 찾을 수 없습니다.")
                            return

                await asyncio.sleep(4)
                
                print("🔗 이미지에 전화 연결 링크 추가 중...")
                # 1. 방금 추가된 이미지 클릭하여 선택
                try:
                    img_sel = "img.se-image-resource"
                    await frame.wait_for_selector(img_sel, state="visible", timeout=10000)
                    images = await frame.locator(img_sel).all()
                    if images:
                        last_image = images[-1]
                        await last_image.scroll_into_view_if_needed()
                        await last_image.click()
                        print("✅ 캔버스에서 배너 이미지 클릭 완료 (툴바 활성화)")
                        await asyncio.sleep(1.5)
                    else:
                        print("❌ 에디터 내에서 이미지를 찾을 수 없습니다.")
                except Exception as e:
                    print(f"❌ 이미지 클릭 중 오류 발생: {e}")

                # 2. 이미지 속성 툴바에서 링크 버튼 클릭
                link_btn_sel = ".se-l-property-toolbar .se-toolbar-item-link > div > button"
                link_btn = frame.locator(link_btn_sel).first
                
                if await link_btn.count() > 0 and await link_btn.is_visible():
                    await link_btn.click()
                    print("✅ 이미지 속성 툴바의 링크 버튼 클릭 성공")
                    await asyncio.sleep(0.5)
                    
                    # 3. 링크 입력창에 연결
                    link_input_sel = ".se-l-property-toolbar .se-toolbar-item-link div > div > input"
                    link_input = frame.locator(link_input_sel).first
                    
                    if await link_input.count() > 0 and await link_input.is_visible():
                        tel_link = f"tel:{phone_number}"
                        await link_input.fill(tel_link)
                        await asyncio.sleep(0.5)
                        
                        # 4. 링크 적용
                        link_confirm_sel = ".se-l-property-toolbar .se-toolbar-item-link div > div > button"
                        confirm_btn = frame.locator(link_confirm_sel).first
                        if await confirm_btn.count() > 0 and await confirm_btn.is_visible():
                            await confirm_btn.click()
                            print(f"✅ 확인 버튼 클릭 완료! 링크({tel_link}) 적용 성공")
                        else:
                            await link_input.press("Enter")
                            print(f"✅ Enter키 입력 완료! 링크({tel_link}) 적용 성공")
                    else:
                        print("❌ 링크 입력창을 찾을 수 없습니다.")
                else:
                    print("❌ 링크 속성 툴바 버튼을 찾을 수 없거나 클릭 실패")
                
            except Exception as e:
                print(f"❌ 배너 업로드 중 오류 발생: {e}")

        async def upload_warning_image(page, frame):
            """거래완료경고 이미지 업로드"""
            banner_path = os.path.join(PROJECT_ROOT, "templates", "거래완료경고.png")
            
            if not os.path.exists(banner_path):
                print(f"⚠️ 경고 이미지를 찾을 수 없습니다: {banner_path}")
                return
            
            print(f"🚨 거래완료경고 이미지 업로드 시도: {banner_path}")
            
            try:
                file_input_sels = selectors['insert']['image']['file_input']
                btn_sels = selectors['insert']['image']['button']
                
                input_found = False
                for sel in file_input_sels:
                    if await frame.locator(sel).count() > 0:
                        await frame.locator(sel).set_input_files(banner_path)
                        input_found = True
                        print("✅ 경고 이미지 파일 설정 완료 (Frame)")
                        break
                
                if not input_found:
                    for sel in file_input_sels:
                        if await page.locator(sel).count() > 0:
                            await page.locator(sel).set_input_files(banner_path)
                            input_found = True
                            print("✅ 경고 이미지 파일 설정 완료 (Page)")
                            break
                            
                if not input_found:
                    async with page.expect_file_chooser() as fc_info:
                        clicked = False
                        for sel in btn_sels:
                            try:
                                btn = frame.locator(sel)
                                if await btn.count() > 0 and await btn.is_visible():
                                    await btn.click()
                                    clicked = True
                                    break
                            except: continue
                        
                        if not clicked:
                            for sel in btn_sels:
                                try:
                                    btn = page.locator(sel)
                                    if await btn.count() > 0 and await btn.is_visible():
                                        await btn.click()
                                        clicked = True
                                        break
                                except: continue
                                
                        if clicked:
                            file_chooser = await fc_info.value
                            await file_chooser.set_files(banner_path)
                            print("✅ 파일 선택기를 통해 경고 이미지 업로드 완료")
                        else:
                            print("❌ 사진 업로드 버튼을 찾을 수 없습니다.")
                            return

                await asyncio.sleep(4)
                
            except Exception as e:
                print(f"❌ 경고 이미지 업로드 중 오류 발생: {e}")

        print("--- 6. 전화 연결 배너 삽입 ---")
        realtor_info = property_data.get('realtor', {}) if property_data else {}
        target_phone = realtor_info.get('mobile') or realtor_info.get('phone') or "010-0000-0000"
        await upload_contact_banner(page, frame, target_phone)

        print("--- 6-2. 거래완료경고 이미지 삽입 ---")
        # 에디터 포커스 복귀 및 이미지 선택 해제를 위해 방향키 조작 후 엔터
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.2)
        await page.keyboard.press("ArrowRight")
        await asyncio.sleep(0.3)
        await page.keyboard.press("Enter")
        await asyncio.sleep(0.5)
        await upload_warning_image(page, frame)

        # [자동화] 도움말 패널이 있다면 닫기
        print("도움말 패널(Help Panel) 체크 중...")
        help_close_sels = ["button.se-help-panel-close-button", ".se-help-panel-close-button"]
        for sel in help_close_sels:
            # Page 체크
            try:
                if await page.locator(sel).count() > 0:
                    if await page.locator(sel).first.is_visible():
                        await page.locator(sel).first.click()
                        print("✅ 도움말 패널 닫힘 (Page)")
                        await asyncio.sleep(0.5)
            except: pass
            
            # Frame 체크
            try:
                if await frame.locator(sel).count() > 0:
                    if await frame.locator(sel).first.is_visible():
                        await frame.locator(sel).first.click()
                        print("✅ 도움말 패널 닫힘 (Frame)")
                        await asyncio.sleep(0.5)
            except: pass

        print("--- 7. 임시저장 ---")
        await page.mouse.move(0, 0)
        saved = False
        
        for draft_sel in selectors['publish']['draft']:
            try:
                btn = frame.locator(draft_sel)
                if await btn.is_visible():
                    await btn.scroll_into_view_if_needed()
                    await btn.click(timeout=5000)
                    print(f"✅ 임시저장 성공! ({draft_sel})")
                    saved = True
                    break
            except:
                continue
        
        if not saved:
            print("⚠️ 임시저장 버튼을 찾지 못했습니다.")

        print("작업 완료. 3초 후 종료됩니다.")
        await asyncio.sleep(3)
        await browser.close()


if __name__ == "__main__":
    if not NAVER_ID or not NAVER_PW:
        print("❌ config/settings.yaml 파일에 naver 아이디와 비밀번호를 먼저 입력해주세요.")
    else:
        # 명령행 인자가 있으면 해당 매물 번호로 실행
        if len(sys.argv) > 1:
            article_no = sys.argv[1]
            print(f"🔍 매물 번호 {article_no} 처리 시작...")
            
            # 파일 경로 설정
            json_path = os.path.join(PROJECT_ROOT, "output", f"property_{article_no}.json")
            md_path = os.path.join(PROJECT_ROOT, "output", "contents", f"blog_{article_no}.md")
            
            if os.path.exists(json_path) and os.path.exists(md_path):
                import json
                
                # 1. JSON 데이터 읽기
                with open(json_path, 'r', encoding='utf-8') as f:
                    raw_data = json.load(f)
                
                # 2. MD 본문 읽기 (제목/본문 분리)
                with open(md_path, 'r', encoding='utf-8') as f:
                    md_lines = f.readlines()
                
                # 첫 줄을 제목으로 사용 (# 제거)
                blog_title = md_lines[0].replace('#', '').strip()
                
                blog_content = "".join(md_lines[1:]).strip()
                
                # 3. 데이터 매핑 (RAW JSON -> Table Format)
                # 네이버 부동산 데이터(raw_data)에서 필요한 필드를 정밀하게 추출합니다.
                title_val = raw_data.get('title', '-')
                area_val = raw_data.get('area_display', '-')
                
                # 면적 분리 및 평형 계산 로직
                supply_area_str = "-"
                private_area_str = "-"
                
                if "/" in area_val:
                    supply_area_str, private_area_str = area_val.split("/")
                elif "(" in area_val:
                    supply_area_str = area_val.split("(")[0].strip()
                    private_area_str = area_val.split("전용")[-1].replace(")", "").strip()
                else:
                    supply_area_str = area_val

                def format_area(area_text):
                    if not area_text or area_text == "-": return "-"
                    display_text = area_text
                    if "㎡" not in display_text:
                        display_text += "㎡"
                    return display_text

                supply_area = format_area(supply_area_str)
                private_area = format_area(private_area_str)

                # 4. 관리비 데이터 조립 (금액 + 고정 문구 3종)
                maint_info = raw_data.get('maintenance_info', [])
                maint_fee_val = maint_info[0] if maint_info else "-"
                
                maint_clauses = [
                    maint_fee_val,
                    "관리규약 등에 따라 부과",
                    "포함 항목(사용료) : 공용관리비, 전기, 수도, 난방비, 기타관리비",
                    "관리비 기준 : 최근 3개월 평균 관리비"
                ]
                # 빈 값 제외하고 <br>로 결합
                full_maint_fee = "<br>".join([c for c in maint_clauses if c and c != "-"])

                # 5. 층수 계산 (고/중/저)
                floor_info = raw_data.get('floor', '-')
                if "/" in floor_info:
                    try:
                        current_floor, total_floor_str = floor_info.split("/")
                        total_floor = int(re.findall(r"\d+", total_floor_str)[0])
                        
                        if current_floor.lower() in ["b", "지하"] or "지하" in current_floor:
                            floor_label = "지하"
                        else:
                            curr_f = int(re.findall(r"\d+", current_floor)[0])
                            if curr_f <= total_floor / 3:
                                floor_label = "저층"
                            elif curr_f <= (total_floor / 3) * 2:
                                floor_label = "중층"
                            else:
                                floor_label = "고층"
                        floor_info = f"{floor_label}/{total_floor_str}"
                    except Exception:
                        pass

                mapped_data = {
                    'summary': {
                        'building_name': title_val,
                        'supply_area': supply_area,
                        'private_area': private_area,
                        'trade_type': raw_data.get('trade_type', '매매'),
                        'price': raw_data.get('price', '-'),
                        'floor_info': floor_info,
                        'available_date': raw_data.get('available_date', '즉시입주 협의가능'),
                        'room_bath_count': raw_data.get('room_bath_count', '-'),
                        'maintenance_fee': full_maint_fee if full_maint_fee else "-"
                    },
                    'detail': {
                        'title': '매물 세부 정보',
                        'building_num': title_val.split()[-1] if ' ' in title_val else '-', 
                        'direction': raw_data.get('direction', '-'),
                        'entrance_type': raw_data.get('entrance_type', '-')
                    },
                    'complex': {
                        'total_buildings': '-', # ㎡에서 추출 안됨
                        'building_use': raw_data.get('building_use', '-'),
                        'total_units': raw_data.get('total_units', '-'), 
                        'parking': raw_data.get('parking', '-'),
                        'heating_type': raw_data.get('heating', '-'),
                        'builder': raw_data.get('builder', '-'),
                        'approval_date': raw_data.get('approval_date', '-'), 
                        'address': raw_data.get('complex_address', '-')
                    },
                    'realtor': {
                        'name': raw_data.get('realtor_name', '랜드월 공인중개사'),
                        'ceo': raw_data.get('realtor_ceo', '-'),
                        'biz_num': '-', # 이미지 데이터에 없음
                        'reg_num': raw_data.get('realtor_reg_num', '-'),
                        'phone': raw_data.get('realtor_phone', '-'),
                        'mobile': raw_data.get('realtor_mobile', '-'),
                        'address': raw_data.get('realtor_address', '-')
                    }
                }
                
                print(f"📑 제목: {blog_title}")
                print(f"📄 본문 길이: {len(blog_content)}자")
                
                tables = generate_property_tables(mapped_data)
                
                blog_content = blog_content.replace('[TABLE_COMPLEX]', tables['complex'])
                blog_content = blog_content.replace('[TABLE_SUMMARY]', tables['summary'])
                blog_content = blog_content.replace('[TABLE_DETAIL]', tables['detail'])
                blog_content = blog_content.replace('[TABLE_REALTOR]', tables['realtor'])
                
                print(f"📊 HTML 테이블 삽입 완료 (본문 길이: {len(blog_content)}자)")
                
                asyncio.run(naver_login_and_write(mapped_data, blog_title, blog_content))
                
            else:
                print("❌ 파일을 찾을 수 없습니다.")
                print(f"- JSON: {json_path}")
                print(f"- MD: {md_path}")
                print("먼저 데이터를 수집하고 콘텐츠를 생성해주세요.")
        
        else:
            # 인자가 없으면 기존 테스트 모드 실행
            print("🚀 테스트 모드로 실행합니다 (매물번호 인자 없음)")
            asyncio.run(naver_login_and_write())
