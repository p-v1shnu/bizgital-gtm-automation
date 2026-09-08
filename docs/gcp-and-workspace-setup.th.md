# บันทึกการตั้งค่าบัญชี Google Workspace / Cloud Identity / GCP

เอกสารนี้บันทึกทุกขั้นตอนที่ทำจริงเพื่อให้ `pele@bizgital.com` เป็นเจ้าของ
Google Cloud organization ของ `bizgital.com` และสร้าง service account
สำหรับสคริปต์ provisioning นี้ ไล่ตั้งแต่ตอนที่ยังไม่มีอะไรเลย จนถึงตอนที่
รัน API ได้จริง

เป้าหมายที่ตั้งไว้ตั้งแต่แรกคือ **ทุกอย่างต้องอยู่ใต้บัญชีบริษัท ไม่ใช่
บัญชี Google ส่วนตัวของใครคนใดคนหนึ่ง** — เอกสารนี้จึงพิเศษกว่าการสมัคร
ทั่วไป เพราะเจอปัญหาที่ไม่คาดคิดระหว่างทางหลายจุด

ถ้าต้องทำซ้ำกับโดเมนอื่นในอนาคต อ่านเอกสารนี้ก่อน จะได้ไม่ต้องเสียเวลา
ไล่แก้ปัญหาเดิมซ้ำอีก

---

## สรุปสั้น ๆ ก่อน (TL;DR)

1. โดเมน `bizgital.com` ไม่เคยมี Google Workspace ตั้งใจสมัครไว้ แต่ Google
   บล็อกการสมัครใหม่เพราะมีร่องรอยการยืนยันอีเมลกับ Google service บางตัว
   ค้างอยู่แบบไม่มีใครรู้ตัว
2. ยืนยันโดเมนแบบทั่วไปผ่าน Search Console **ไม่พอ** ต้องผ่านเส้นทางสมัคร
   Google Workspace Business trial แบบเฉพาะเจาะจงถึงจะ "เคลม" โดเมนคืนได้
3. หลังเคลมสำเร็จ เพิ่ม **Cloud Identity Free** แล้วยกเลิก Business trial
   ทิ้ง (ไม่ต้องเสียเงิน)
4. สร้าง GCP Project ใต้ organization `bizgital.com`
5. เจอ Organization Policy บล็อกการสร้าง service account key โดยอัตโนมัติ
   (ฟีเจอร์ความปลอดภัยเริ่มต้นของ org ใหม่) ต้อง override เฉพาะ project
6. สร้าง key ได้สำเร็จ → เอาไปใช้กับสคริปต์และเพิ่มสิทธิ์ใน GTM

---

## ขั้นที่ 1 — เช็คว่ามี Google Workspace อยู่แล้วหรือยัง

ก่อนจะสมัครอะไร เช็คให้แน่ใจก่อนว่าไม่มีของเดิมอยู่:

- **ลองใส่อีเมลบริษัทที่ `accounts.google.com`** → ถ้าขึ้น *"Couldn't find
  this account"* แปลว่าไม่มีบัญชี Google ผูกกับอีเมลนั้นเลย (กรณีของเราคือ
  แบบนี้ — `pele@bizgital.com` ไม่เคยมีมาก่อน)
- **เช็ค DNS ที่ Cloudflare** — กรองหาคำว่า `google`
  - ไม่มี MX ของ Google (`aspmx.l.google.com`) → ไม่ได้ใช้ Gmail รับส่งเมล
  - ไม่มี SPF ที่มี `include:_spf.google.com` → ไม่เคยส่งเมลผ่าน Google
  - **แต่เจอ TXT record `google-site-verification=...` อยู่ 1 ตัว** — นี่คือ
    เบาะแสสำคัญ: มีคนเคยยืนยันโดเมนนี้กับ Google service บางตัว (อาจเป็น
    Search Console, Google Ads หรืออื่น ๆ) แต่ระบุชัดเจนไม่ได้ว่าอันไหน

สรุปตอนนั้น: **ไม่มี Workspace ที่ตั้งใจสมัคร แต่มีร่องรอยว่าเคยมีคนแตะ
Google service ด้วยอีเมลโดเมนนี้**

---

## ขั้นที่ 2 — สมัคร Cloud Identity ตรง ๆ ไม่ผ่าน

ลองไปที่ `workspace.google.com/signup/gcpidentity/welcome` ใส่โดเมน
`bizgital.com` → เจอข้อความ:

> Someone at your organization is already using your domain for a Google
> service. To sign up for a new Google service, you'll need to verify
> ownership of this domain.

ปุ่ม Next กดไม่ผ่าน แม้จะลองยืนยันความเป็นเจ้าของโดเมนผ่าน **Search
Console** (Add property → Domain → ยืนยันผ่าน DNS TXT ที่ Cloudflare)
สำเร็จแล้วก็ตาม — **ยืนยันแบบ Search Console คนละระบบกับที่ Cloud Identity
ต้องการ ไม่ปลดล็อกให้กัน**

---

## ขั้นที่ 3 — วิธีแก้ที่ถูกต้องจาก Google เอง

หาข้อมูลจากหน้า Google Support โดยตรง
([Can't sign up my domain for a Google service](https://support.google.com/a/answer/80610))
พบว่านี่คือกรณีที่ Google เรียกว่า **"email-verified account"** — มีคนใน
โดเมนเคยยืนยันอีเมลกับ Google service ตัวใดตัวหนึ่งไว้แบบไม่รู้ตัว ทำให้
Google สร้าง organization แบบเบา ๆ (unmanaged) ผูกไว้กับโดเมนโดยอัตโนมัติ

วิธีแก้มี **3 ขั้นตายตัว** ไม่ใช่การสมัคร Cloud Identity ตรง ๆ:

### ขั้น 3.1 — สมัคร Google Workspace แบบ email verification

ใช้ลิงก์สมัคร **Business edition** (ไม่ใช้ Essentials เพราะมีเงื่อนไข
บังคับอัปเกรดแถมมาด้วย) แล้ว **ใส่อีเมลที่ต้องการให้เป็นแอดมินตัวจริง**
คือ `pele@bizgital.com` — ยืนยันผ่านโค้ดที่ส่งไปกล่องเมล Outlook (ไม่ใช่
DNS ในขั้นนี้)

ระหว่างทางเจอหน้า **"Existing subscription found"** ที่ให้ใส่อีเมลที่มี
อยู่แล้วในระบบ — **ห้ามเดาใส่** เพราะไม่รู้อีเมลที่มีอยู่จริง ปิดหน้านั้น
แล้วลองใหม่ด้วยเส้นทางสมัคร Business ตรง ๆ (ไม่ผ่านหน้าเช็คแบบนั้น) จนมา
ถึงหน้า **"Create a username"** ที่ให้ตั้ง `pele@bizgital.com` เป็น
username ได้สำเร็จ — ตรงนี้คือสัญญาณว่าผ่านจุดบล็อกเดิมแล้ว

จากนั้นเลือกแพ็กเกจ **Starter** → กด **"Try at no cost for 14 days"** →
ตั้งรหัสผ่าน → **Agree and continue**

### ขั้น 3.2 — ยืนยันโดเมนเพื่อ "ปลดล็อก" (จุดที่ merge ของเก่าเข้ามา)

หลังสมัครเสร็จ เข้าสู่ **Admin Console** ครั้งแรก (เลือก "Continue with
recommended setup steps" ตอนถูกถามว่าจะทำอะไรก่อน) แล้วเจอหน้า:

> **Unlock admin features**
> Looks like other teams at your organization signed up for a Google
> service using email verification. They'll be merged with your team...
> Unlock admin features by **September 15, 2026**. After that date, other
> admins will have the option to take over management.

กด **Agree and Continue** → เจอหน้า **Review subscription** โชว์รายชื่อ
organization ที่จะถูกรวมเข้ามา:

| Organization | Edition | Admin email |
|---|---|---|
| BIZGITAL Company Limited (ของเรา) | Business Starter | pele@bizgital.com |
| Youtthasone's Workspace | Essentials Starter | youtthasone@bizgital.com |

**`youtthasone@bizgital.com` คือบัญชีลึกลับที่ทำให้โดเมนถูกล็อกไว้ตลอด**
— ถามคนในบริษัทแล้วไม่มีใครรู้จัก (ชื่อฟังดูเป็นชื่อลาว อาจเป็นพนักงาน/
พาร์ทเนอร์เก่าฝั่งตลาดลาวที่บริษัทดูแลอยู่ แต่ไม่ยืนยันแน่ชัด) เนื่องจากมี
เดดไลน์ 15 ก.ย. ที่ถ้าไม่ทำก่อน คนอื่นจะมีสิทธิ์เข้ามาคุมองค์กรแทนได้ จึง
ตัดสินใจกด **Continue** ไปเลยโดยไม่รอผลสอบถาม — การ merge นี้ไม่ได้ลบ
ข้อมูลอะไร แค่เอา org นั้นมาอยู่ใต้การดูแลของเราเท่านั้น

กด Continue แล้วเจอหน้า **"Changes are in progress — may take up to 12
hours"** (ในทางปฏิบัติเสร็จข้ามคืนเดียว เร็วกว่าที่ระบุไว้)

### ขั้น 3.3 — เพิ่ม Cloud Identity Free แล้วยกเลิก Business trial

พอกลับมาเช็คอีกที **Admin → Account → Domains** ขึ้นสถานะ:

> ✅ You're all set to manage your organization.
> bizgital.com — Primary Domain — Verified

จากนั้น:

1. **Billing → Buy or upgrade** → เลื่อนหาหมวด **"Get more with add-ons"**
   → **Google Cloud management** → **Cloud Identity Free ($0)** → Explore
   → เพิ่มเข้าบัญชี
2. เช็คที่ **Billing → Subscriptions** ว่าขึ้น **Cloud Identity Free —
   Active — Free plan (no charges)**
3. คลิกเข้า **Google Workspace Business Starter** ที่ยังค้างอยู่ → กด
   **Cancel subscription** → หน้าที่เสนอทางเลือกอื่น (User management /
   Domain Change / Something else) **ไม่ต้องกดอะไรในนั้น** เลื่อนลงไปกด
   **"Continue to cancel"** ตรง ๆ

ผลลัพธ์สุดท้าย: เหลือแค่ **Cloud Identity Free** ตัวเดียวที่ Active ไม่มี
ค่าใช้จ่ายใด ๆ ค้างอยู่

> ⚠️ **ลำดับสำคัญ:** ต้องเพิ่ม Cloud Identity Free ให้ Active ก่อน แล้ว
> ค่อยยกเลิก Business trial ทีหลัง ถ้ายกเลิกก่อนโดยที่ยังไม่มี subscription
> อื่นมาแทน อาจเสี่ยงให้ระบบเสนอลบทั้ง organization ทิ้งไปเลย

> 📝 **ค้างไว้:** บัญชี `youtthasone@bizgital.com` ยังอยู่ในระบบ (แนะนำให้
> **Suspend** ก่อนแทนการ Delete ทันที เผื่อมีใครในบริษัทนึกออกทีหลังว่า
> เป็นของใคร ค่อยลบถาวรทีหลังถ้าไม่มีใครทัก)

---

## ขั้นที่ 4 — สร้าง GCP Project ใต้ Organization

1. เข้า `console.cloud.google.com` ด้วย `pele@bizgital.com`
2. **New Project** → ตั้งชื่อ `bizgital-gtm-automation`
3. ช่อง **Organization / Parent resource** → กด **Browse** → เลือก
   `bizgital.com`

⚠️ ตอนแรกกด Browse แล้ว**ไม่เจอ** `bizgital.com` ในลิสต์ ทั้งที่ล็อกอิน
ถูกอีเมลแล้ว (ยืนยันจากหน้า Admin Console ว่าเป็น user ใน organization
จริง) — สาเหตุคือ **Cloud Identity กับ Google Cloud Resource Manager เป็น
คนละระบบ ต้องรอ sync กัน** ในเคสนี้รอไม่นาน (ไม่กี่ชั่วโมง) แล้วลองใหม่ก็
เจอ ถ้าไม่อยากรอ สร้าง project แบบ "No organization" ไปก่อนก็ได้ เพราะ
**Project ID ไม่เปลี่ยนตอนย้ายเข้า organization ทีหลัง** — ไม่กระทบ service
account/key/สิทธิ์ GTM ที่จะตั้งค่าต่อ

4. เปิดใช้ **Tag Manager API** (ช่อง Search บนสุด พิมพ์ "Tag Manager API"
   → Enable)

---

## ขั้นที่ 5 — สร้าง Service Account

1. **IAM & Admin → Service Accounts → Create service account**
   - Name: `gtm-provisioner`
   - ขั้น Permissions (optional) และ Principals with access (optional) →
     **ข้ามทั้งคู่** ไม่ต้องให้ role อะไรเลย เพราะสิทธิ์ที่ใช้จริงมาจากฝั่ง
     GTM ไม่ใช่ IAM ของ GCP
2. เข้า service account ที่สร้าง → แท็บ **Keys → Add key → Create new key
   → JSON**

### ปัญหาที่เจอ: สร้าง key ไม่ได้

ขึ้น error:

> **Service account key creation is disabled**
> An Organization Policy that blocks service accounts key creation has been
> enforced on your organization.
> Enforced Organization Policies IDs:
> `iam.managed.disableServiceAccountKeyCreation`

นี่คือ Organization Policy ที่ Google เปิดให้อัตโนมัติกับ organization ที่
เพิ่งสร้างใหม่ (ส่วนหนึ่งของ "Secure by Default") เพื่อผลักดันให้ใช้วิธี
authen ที่ปลอดภัยกว่า (เช่น Workload Identity Federation) แทนไฟล์ key —
แต่สคริปต์ของเราต้องการไฟล์ JSON key จริง ๆ

**วิธีแก้ — ปลดล็อกเฉพาะ project นี้ ไม่ปลดทั้ง organization:**

1. **IAM & Admin → Organization Policies**
2. เช็คด้านบนว่ากำลังดูที่ระดับ **project `bizgital-gtm-automation`** อยู่
   (ไม่ใช่ระดับ organization)
3. ค้นหา **"Disable service account key creation"**
4. คลิกเข้าไป → **Edit policy**
5. **Policy source** → เลือก **"Override parent's policy"**
6. กด **"Add a rule"** (จำเป็น ไม่งั้น Google จะฟ้องว่า "At least one rule
   is required")
7. ตั้ง enforcement เป็น **Off**
8. กด **"Set policy"**
9. กลับไปที่ Service Accounts → Keys → Add key → Create new key → JSON —
   คราวนี้สร้างผ่านแล้ว

เก็บไฟล์ที่ได้ไว้ที่ `secrets/service-account.json` (อยู่ใน `.gitignore`
แล้ว ไม่หลุดเข้า git แน่นอน) และจดอีเมล service account ไว้ หน้าตาจะเป็น:

```
gtm-provisioner@bizgital-gtm-automation.iam.gserviceaccount.com
```

---

## ขั้นที่ 6 — เพิ่มสิทธิ์ใน GTM

เข้า `tagmanager.google.com` → **Admin → Account** (คอลัมน์ Account ไม่ใช่
Container) → **User Management → +** เพิ่ม 2 คน เป็น **Administrator**
ทั้งคู่:

| อีเมล | บทบาท |
|---|---|
| `pele@bizgital.com` | แอดมินที่เป็นมนุษย์ ดูแลผ่าน UI ได้ |
| `gtm-provisioner@bizgital-gtm-automation.iam.gserviceaccount.com` | ตัวที่สคริปต์ใช้ authen |

ต้องเป็นสิทธิ์ระดับ **Account** เท่านั้น เพราะสคริปต์ต้อง **สร้าง
container ใหม่** ซึ่งสิทธิ์ระดับ container เพียงอย่างเดียวไม่พอ จะได้ HTTP
403 กลับมา

## ขั้นที่ 7 — เพิ่มสิทธิ์ใน GA4 (คนละระบบกับ GTM)

เป็นคนละผลิตภัณฑ์ คนละหน้า Admin เลย — **การเป็น Administrator ใน GTM ไม่ได้
แปลว่าจะมีสิทธิ์ใน GA4 ด้วย** ต้องไปเพิ่มแยกต่างหาก

เข้า `analytics.google.com` → **Admin → Account Access Management** (ของ
**Account** ที่ตั้งไว้ใน `ga4.account_id` เช่น `216060784` — ไม่ใช่หน้าของ
Property) → เพิ่มอีเมล service account ตัวเดิม (`gtm-provisioner@...`) →
ให้สิทธิ์ **Editor**

ถ้าลืมขั้นนี้ ตอนสคริปต์พยายามสร้าง GA4 property จะได้ HTTP 403 กลับมา
พร้อมข้อความบอกตรง ๆ ว่าต้องเพิ่มสิทธิ์ตรงนี้

---

## เช็คลิสต์สรุป

- [x] เช็คว่าไม่มี Workspace เดิมอยู่ (accounts.google.com + DNS)
- [x] เจอ block "domain already in use" ตอนสมัคร Cloud Identity ตรง ๆ
- [x] สมัคร Business edition ด้วย `pele@bizgital.com` (email verification)
- [x] ยืนยันโดเมนผ่าน DNS → merge บัญชีเก่า (`youtthasone@bizgital.com`)
      เข้ามา
- [x] เพิ่ม Cloud Identity Free (ก่อน) → ยกเลิก Business trial (ทีหลัง)
- [x] สร้าง GCP Project ใต้ organization `bizgital.com`
- [x] เปิด Tag Manager API
- [x] สร้าง Service Account
- [x] แก้ Organization Policy ที่บล็อกการสร้าง key → สร้าง key สำเร็จ
- [x] เพิ่ม `pele@bizgital.com` และอีเมล service account เข้า GTM Account
      เป็น Administrator
- [x] รัน `provision_gtm.py --dry-run` แล้วรันจริง — สร้าง container ทดสอบ
      สำเร็จ, entity count ตรงครบ, ตรวจด้วยตาแล้วว่าทุก tag ผูก trigger
      ถูกตัว, ลบ container ทดสอบทิ้งแล้ว. **ระบบพร้อมใช้กับร้านจริง**
- [ ] (ทำทีหลังได้) ตัดสินใจเรื่องบัญชี `youtthasone@bizgital.com` ค้างไว้ —
      suspend หรือ delete
- [ ] เพิ่มอีเมล service account เข้า **GA4 Account** (`ga4.account_id`) ที่
      `analytics.google.com` → Admin → Account Access Management เป็น
      Editor (คนละขั้นตอนกับสิทธิ์ GTM ข้างบน — ต้องทำเพิ่มก่อนใช้ฟีเจอร์
      สร้าง GA4 property อัตโนมัติ)
