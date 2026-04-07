"""
批量采集点选验证码裁剪图 - GitHub Actions版
每采集500张打包发送到QQ邮箱
"""

import base64
import os
import time
import smtplib
import zipfile
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from io import BytesIO

import ddddocr
from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import NoSuchElementException, TimeoutException

# ══════════════════════════════════════════
ACCOUNT   = os.environ["LIB_ACCOUNT"]
PASSWORD  = os.environ["LIB_PASSWORD"]
QQ_ADDR   = os.environ["QQ_ADDR"]       # 你的QQ邮箱，如 123456@qq.com
QQ_SMTP_PASS = os.environ["QQ_SMTP_PASS"]  # QQ邮箱授权码（不是登录密码）

TARGET    = 3000
BATCH     = 500       # 每500张发一次
SAVE_DIR  = "crops"
BG_DIR    = "crops/bg"
# ══════════════════════════════════════════

os.makedirs(SAVE_DIR, exist_ok=True)
os.makedirs(BG_DIR,   exist_ok=True)

ocr_cls = ddddocr.DdddOcr(det=False, use_gpu=False, show_ad=False)
det     = ddddocr.DdddOcr(det=True,  use_gpu=False, show_ad=False)


def make_driver():
    options = ChromeOptions()
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--headless=new')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    # GitHub Actions里chromedriver在PATH中，直接用Service
    service = Service()
    return webdriver.Chrome(service=service, options=options)


def send_email_with_zip(zip_path, batch_num, total_collected):
    """把zip文件作为附件发送到QQ邮箱"""
    print(f"正在发送第{batch_num}批邮件...")
    msg = MIMEMultipart()
    msg["From"]    = QQ_ADDR
    msg["To"]      = QQ_ADDR
    msg["Subject"] = f"验证码裁剪图 第{batch_num}批 共{total_collected}张"

    body = f"第{batch_num}批，本批500张，累计{total_collected}张，见附件。"
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with open(zip_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition",
                    f"attachment; filename={os.path.basename(zip_path)}")
    msg.attach(part)

    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465) as server:
            server.login(QQ_ADDR, QQ_SMTP_PASS)
            server.sendmail(QQ_ADDR, QQ_ADDR, msg.as_string())
        print(f"第{batch_num}批邮件发送成功")
    except Exception as e:
        print(f"邮件发送失败: {e}")


def pack_and_send(batch_files, batch_num, total_collected):
    """打包指定文件列表并发送"""
    zip_path = f"batch_{batch_num:03d}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fpath in batch_files:
            zf.write(fpath, os.path.basename(fpath))
    size_mb = os.path.getsize(zip_path) / 1024 / 1024
    print(f"已打包 {len(batch_files)} 张，压缩包大小: {size_mb:.1f}MB")

    # QQ邮箱附件上限50MB，超了就提示但不发
    if size_mb > 48:
        print(f"警告：压缩包超过48MB，跳过发送，文件保留在runner上")
    else:
        send_email_with_zip(zip_path, batch_num, total_collected)

    os.remove(zip_path)


def login(driver):
    driver.get('http://libseat.lnu.edu.cn/#/login')
    time.sleep(1)
    while True:
        try:
            username_input = driver.find_element(By.CSS_SELECTOR, 'input[placeholder="请输入账号"]')
        except NoSuchElementException:
            print("未找到登录框，等待3秒重试...")
            time.sleep(3)
            driver.refresh()
            continue

        username_input.clear()
        username_input.send_keys(ACCOUNT)
        driver.find_element(By.CSS_SELECTOR, 'input[placeholder="请输入密码"]').clear()
        driver.find_element(By.CSS_SELECTOR, 'input[placeholder="请输入密码"]').send_keys(PASSWORD)

        img_elem = driver.find_element(By.CSS_SELECTOR, '.captcha-wrap img')
        img_src  = img_elem.get_attribute("src")
        if not img_src.startswith("data:image"):
            time.sleep(1)
            continue

        img_bytes = base64.b64decode(img_src.split(",")[1])
        code = ocr_cls.classification(img_bytes)
        print(f"登录验证码: {code}")
        if len(code) != 4:
            img_elem.click()
            time.sleep(1)
            continue

        driver.find_element(By.CSS_SELECTOR, 'input[placeholder="请输入验证码"]').clear()
        driver.find_element(By.CSS_SELECTOR, 'input[placeholder="请输入验证码"]').send_keys(code)
        driver.find_element(By.XPATH, "//button[contains(@class, 'login-btn')]").click()
        time.sleep(2)

        try:
            driver.find_element(By.CLASS_NAME, "header-username")
            print("登录成功！")
            return
        except NoSuchElementException:
            print("登录失败，重试...")
            time.sleep(1)


def open_captcha(driver):
    try:
        el = WebDriverWait(driver, 8).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".el-select__caret.el-input__icon.el-icon-arrow-up"))
        )
        driver.execute_script("arguments[0].click();", el)
        time.sleep(0.8)
        WebDriverWait(driver, 8).until(
            EC.element_to_be_clickable((By.XPATH, "//li/span[text()='崇山校区图书馆']"))
        ).click()
        time.sleep(1.5)
    except Exception as e:
        print(f"切换校区出错: {e}")

    try:
        room = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.XPATH, '//*[contains(@class,"room-name") and contains(text(),"二楼书库南")]'))
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", room)
        driver.execute_script("arguments[0].click();", room)
        time.sleep(1)
    except Exception as e:
        print(f"进入自习室出错: {e}")

    try:
        seat = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.XPATH, '//div[contains(@class, "seat-name") and text()="91"]'))
        )
        seat.click()
        time.sleep(0.5)
    except Exception as e:
        print(f"点击座位出错: {e}")

    try:
        WebDriverWait(driver, 8).until(
            EC.element_to_be_clickable((By.XPATH, '(//div[@class="times-roll"])[1]//label[normalize-space(text())="09:00"]'))
        ).click()
        time.sleep(1.5)
        rolls = driver.find_elements(By.CLASS_NAME, "times-roll")
        if len(rolls) >= 2:
            for label in rolls[1].find_elements(By.TAG_NAME, "label"):
                if label.text.strip() == "15:00":
                    label.click()
                    break
        time.sleep(0.5)
        btn = WebDriverWait(driver, 8).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".el-button.submit-btn.el-button--default"))
        )
        btn.click()
        time.sleep(1.5)
    except Exception as e:
        print(f"选时间/提交出错: {e}")


def collect_one_round(driver, collected, batch_buffer):
    try:
        WebDriverWait(driver, 6).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "img.captcha-text"))
        )
    except TimeoutException:
        print("未出现验证码弹窗，跳过")
        return collected, batch_buffer

    bg_elem = driver.find_element(By.CSS_SELECTOR, ".captcha-modal-content img")
    bg_src  = bg_elem.get_attribute("src")
    if not bg_src or not bg_src.startswith("data:image"):
        return collected, batch_buffer

    bg_bytes = base64.b64decode(bg_src.split(",")[1])
    bg_image = Image.open(BytesIO(bg_bytes))

    hint_elem  = driver.find_element(By.CSS_SELECTOR, "img.captcha-text")
    hint_bytes = base64.b64decode(hint_elem.get_attribute("src").split(",")[1])
    hint_raw   = ocr_cls.classification(hint_bytes)
    hint_chars = [c for c in hint_raw if '\u4e00' <= c <= '\u9fff']

    bboxes = det.detection(bg_bytes)
    if not bboxes:
        print("未检测到任何bbox，刷新")
        driver.find_element(By.CSS_SELECTOR, "img.refresh").click()
        time.sleep(1)
        return collected, batch_buffer

    ts = time.strftime("%Y%m%d_%H%M%S")
    hint_str = "".join(hint_chars) if hint_chars else "unknown"
    bg_image.save(f"{BG_DIR}/{ts}_hint{hint_str}.png")

    auto_count = 0
    for n, bbox in enumerate(bboxes):
        x1, y1, x2, y2 = bbox
        pad = 5
        crop = bg_image.crop((
            max(0, x1 - pad), max(0, y1 - pad),
            min(bg_image.width, x2 + pad), min(bg_image.height, y2 + pad)
        ))

        recognized = ocr_cls.classification(crop)
        han_chars = [c for c in recognized if '\u4e00' <= c <= '\u9fff']
        if han_chars:
            label = han_chars[0]
            auto_count += 1
        else:
            label = "TODO"

        save_path = f"{SAVE_DIR}/{ts}_{n}_{label}.png"
        crop.save(save_path)
        batch_buffer.append(save_path)
        collected += 1

    print(f"本轮保存{len(bboxes)}张（提示字:{hint_chars}，自动识别:{auto_count}/{len(bboxes)}），累计:{collected}")

    try:
        driver.find_element(By.CSS_SELECTOR, "img.refresh").click()
        time.sleep(1)
    except Exception:
        pass

    return collected, batch_buffer


def main():
    driver = make_driver()
    collected  = 0
    batch_num  = 0
    batch_buffer = []   # 记录当前批次的文件路径

    try:
        login(driver)
        open_captcha(driver)
        print(f"\n开始采集，目标: {TARGET} 张\n")

        while collected < TARGET:
            collected, batch_buffer = collect_one_round(driver, collected, batch_buffer)

            # 每500张发一次邮件
            if len(batch_buffer) >= BATCH:
                batch_num += 1
                pack_and_send(batch_buffer[:BATCH], batch_num, collected)
                batch_buffer = batch_buffer[BATCH:]  # 超出部分留到下一批

            if collected > 0 and collected % 100 == 0:
                print("刷新页面防止超时...")
                driver.refresh()
                time.sleep(2)
                open_captcha(driver)

        # 发送剩余不足500张的部分
        if batch_buffer:
            batch_num += 1
            pack_and_send(batch_buffer, batch_num, collected)

        print(f"\n✓ 采集完成！共 {collected} 张")

    except KeyboardInterrupt:
        print(f"\n手动停止，已采集 {collected} 张")
        if batch_buffer:
            batch_num += 1
            pack_and_send(batch_buffer, batch_num, collected)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()