# บันทึกการตั้งค่า Meta Marketing API

เอกสารนี้บันทึกขั้นตอนที่ทำจริงเพื่อให้ `meta_client.py` มี credential
สำหรับสร้าง Meta Pixel อัตโนมัติ — คนละระบบกับ Google (GTM/GA4) โดยสิ้นเชิง
ไม่มี credential ตัวเดียวที่ครอบคลุมทุกอย่างเหมือน service account ของ
Google ต้องผ่าน 4 ขั้นตอน ทำใน **2 หน้าเว็บที่ต่างกัน**:
`developers.facebook.com` (สร้าง App) และ `business.facebook.com`
(สร้าง System User + token)

---

## ขั้นที่ 1 — สร้าง App

ไปที่ `developers.facebook.com` → **My Apps → Create App** → เลือก use case
**"Create & manage ads with Marketing API"**

ระหว่างสร้าง ต้องผูก App เข้ากับ **Business Portfolio** ที่เป็นเจ้าของ
ad account ที่จะใช้ — จำเป็นมากเพราะ System User จะสร้าง token ให้ App
ที่ Business ไม่ได้เป็นเจ้าของไม่ได้ เช็คได้จากรายการ **"Business and
access verification"** ในหน้า Dashboard ของ App ถ้าขึ้นเครื่องหมายถูก
สีเขียวแล้วแปลว่าผ่าน

**ไม่ต้องทำรายการอื่นในเช็คลิสต์** — `Facebook Login for Business`,
`App Review`, `Publish` เป็นของ App ที่จะเปิดให้คนทั่วไปใช้งาน (public/
consumer app) เราไม่ publish App นี้เลย ปล่อยไว้ในสถานะ Development
ตลอดไป ใช้งานผ่าน System User Token เท่านั้น

## ขั้นที่ 2 — สร้าง System User

ไปที่ `business.facebook.com` → Business Settings → **Users → System
Users** → **Add**

เลือก **Employee access** ไม่ใช่ Admin — Admin System User มีอำนาจกว้าง
ระดับทั้ง Business งานนี้แค่ต้องการสร้าง pixel ใน ad account เดียว การใช้
Employee + จำกัดสิทธิ์เฉพาะ asset (ขั้นที่ 4) ปลอดภัยกว่าตามหลัก
least privilege

## ขั้นที่ 3 — สร้าง Token

ที่ System User → **Generate New Token** → เลือก App จากขั้นที่ 1 →
expiration เลือก **Never** → permission เลือกแค่ **`ads_management`**

### ถ้า `ads_management` ไม่โผล่มาให้เลือก

แปลว่า App ยังไม่ได้ "ขอ" permission ตัวนี้ไว้ ต้องไปเพิ่มก่อน:

1. กลับไปที่หน้า Dashboard ของ App (`developers.facebook.com`) →
   **Use cases** → คลิกเข้า use case "Create & manage ads" → **Permissions
   and features**
2. หา `ads_management` ในลิสต์ ถ้าสถานะยังไม่ขึ้น **"Ready for testing"**
   ให้ใช้เมนู **Actions** ข้าง ๆ เพื่อเพิ่มเข้า use case
3. **"Ready for testing" คือสถานะที่ต้องการแล้ว** — แปลว่า Standard Access
   ปลดล็อกทันที (ใช้กับ ad account ของตัวเองได้เลย) ไม่ต้องทำอะไรเพิ่ม
   **ห้ามกด "Go to App Review"** เด็ดขาด เพราะอันนั้นสำหรับ Advanced
   Access (จัดการ ad account ของคนอื่น) ซึ่งสคริปต์นี้ไม่ได้ทำและไม่จำเป็น
4. กลับไปหน้า Generate Token ใหม่ — `ads_management` จะโผล่มาให้เลือกแล้ว

**Token โชว์ให้เห็นแค่ครั้งเดียว** copy ไปวางที่ `secrets/meta-access-token.txt`
ทันที (ในไฟล์มีแค่ token อย่างเดียว ไม่ใส่อะไรอื่น) — ปิดหน้าไปแล้วดูซ้ำ
ไม่ได้ ต้อง revoke แล้วสร้างใหม่เท่านั้น

## ขั้นที่ 4 — Assign Ad Account

ยังอยู่ที่หน้า System User ตัวเดิม → แท็บ **Assigned assets** → ช่อง
search พิมพ์เลข ad account (ตัวเดียวกับที่จะใส่ใน `meta.ad_account_id`
ของ `config.yaml` โดยไม่ต้องมี `act_` นำหน้า) → เพิ่มด้วยสิทธิ์
**Full access**

ถ้าข้ามขั้นนี้ ต่อให้ token มี permission ถูกต้องก็ยังเรียก
`POST /act_<id>/adspixels` ไม่ผ่าน จะได้ HTTP 403 กลับมา — permission
ของ token กับสิทธิ์เข้าถึง asset เป็นคนละเรื่องที่ต้องผ่านทั้งคู่

---

## เรื่องการตั้งชื่อ

Pixel ที่สร้างผ่านสคริปต์จะตั้งชื่อว่า `<ชื่อร้าน> - Dataset` ตรงกับ
convention เดิมที่ตั้งด้วยมือมาก่อน (ดูหัวข้อ "Two names for two different
naming conventions" ใน README หลักประกอบ)
