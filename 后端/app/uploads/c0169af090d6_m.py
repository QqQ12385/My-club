# -*- coding: utf-8 -*-
# 讨论：按证件照尺寸（1寸）裁剪图片（Pillow + OpenCV 人脸识别）
# 安装依赖：pip install pillow opencv-python
# 使用：把有人脸的生活照命名为 photo.jpg，和本脚本放同一文件夹，直接运行

import cv2
from PIL import Image

# 1寸证件照：25mm × 35mm，300dpi 下即 295 × 413 像素
CERT_W, CERT_H = 295, 413

# ---------- 1. 读图 + 人脸检测 ----------
img = cv2.imread("photo.jpg")
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)      # 转灰度图，检测更快

# 加载 OpenCV 自带的人脸级联分类器（haar 级联）
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)
faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1,
                                      minNeighbors=5, minSize=(80, 80))

if len(faces) == 0:
    raise SystemExit("未检测到人脸，请换一张更清晰的正脸照片")

# 取最大的人脸（面积最大 = 主体）
x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
print(f"检测到人脸：位置({x},{y}) 大小 {w}×{h}")

# ---------- 2. 在原图上画矩形框（提交用） ----------
boxed = img.copy()
cv2.rectangle(boxed, (x, y), (x + w, y + h), (0, 255, 0), 3)   # 绿色框，线宽3
cv2.imwrite("photo_boxed.jpg", boxed)                          # 带矩形框的原图

# ---------- 3. 以人脸为中心，按 1 寸比例裁剪 ----------
# 脸只占证件照的上半部分，所以裁剪窗口中心取“脸部中心偏下”，头顶要留空间
cx = x + w // 2                 # 脸的水平中心
cy = y + int(h * 0.75)          # 竖直中心取脸部偏下（让头发/头顶有留白）

# 让裁剪窗口符合 295:413 的宽高比，且面积不小于证件照
crop_w = max(int(h * CERT_W / CERT_H * 1.8), CERT_W)   # 窗口宽 ≈ 脸宽×(1.8倍系数换算)
crop_h = int(crop_w * CERT_H / CERT_W)                 # 按比例求窗口高

# 计算窗口左上角，并把窗口夹在图片范围内（防止越界）
left = max(0, min(cx - crop_w // 2, img.shape[1] - crop_w))
top  = max(0, min(cy - crop_h // 2, img.shape[0] - crop_h))

# Pillow 完成裁剪 + 缩放到 295×413
pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
result = pil.crop((left, top, left + crop_w, top + crop_h))
result = result.resize((CERT_W, CERT_H), Image.LANCZOS)
result.save("photo_1inch.jpg", quality=95)
print("已保存：photo_boxed.jpg（带人脸框）、photo_1inch.jpg（1寸证件照 295×413）")
