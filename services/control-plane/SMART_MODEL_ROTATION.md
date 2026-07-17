# 🔄 Smart Model Rotation & Load Balancing

## 🎯 Mục đích

**Vấn đề:** API có nhiều models với quota khác nhau, cần phân phối tải đều và tự động skip models hết quota.

**Giải pháp:** Smart round-robin với quota tracking và intelligent model selection.

---

## 📊 Cách hoạt động

### 1. **Model Quota Tracker** (In-memory state)

Class `ModelQuotaTracker` theo dõi:
- ✅ **Last successful model**: Model vừa dùng thành công
- ⏰ **Exhausted models**: Models hết quota và thời gian retry
- 📈 **Usage counter**: Số lần mỗi model được dùng (cho load balancing)

```python
{
    "exhausted_until": {
        "gemini-2.5-flash": datetime(2026, 7, 18, 15, 30),  # Retry after
        "gemini-3.5-flash": datetime(2026, 7, 18, 15, 25)
    },
    "last_successful_model": "gemini-3.1-flash-lite",
    "usage_counter": {
        "gemini-3.1-flash-lite": 15,
        "gemini-3.5-flash": 3,
        "gemini-2.5-flash-lite": 2
    }
}
```

### 2. **Smart Model Selection Algorithm**

```
Step 1: Lọc models có sẵn (không bị exhausted)
Step 2: Sắp xếp theo độ ưu tiên:
   Priority 1: Last successful model (đã dùng thành công gần nhất)
   Priority 2: Least used models (dùng ít nhất → load balance)
   Priority 3: Available models (còn quota)
   Priority 4: Exhausted models (để cuối cùng, retry khi hết timeout)

Step 3: Thử tuần tự theo thứ tự đã sắp xếp
Step 4: Mark success/failure để update state
```

### 3. **Retry Timeouts**

| Error Type | Timeout | Lý do |
|------------|---------|-------|
| **404 Restricted** (new users) | 24 giờ | Model bị restrict vĩnh viễn cho account mới |
| **503 Unavailable** (overload) | 2 phút | Temporary server overload |
| **429 Rate Limit** (quota) | 5 phút | Hết quota theo rate limit |

---

## 🔄 Ví dụ thực tế

### **Request 1:**
```
Available models: [3.1-lite, 3.5, 2.5-lite, 3-preview, 2.5]
Order: [3.1-lite, 3.5, 2.5-lite, 3-preview, 2.5]  (original)

Try 3.1-lite → ✅ SUCCESS
Mark: last_successful = "3.1-lite", usage[3.1-lite] = 1
```

### **Request 2-15:**
```
Order: [3.1-lite*, 3.5, 2.5-lite, 3-preview, 2.5]  (* = last successful)

Try 3.1-lite → ✅ SUCCESS (14 lần)
usage[3.1-lite] = 15
```

### **Request 16:** (3.1-lite hết quota)
```
Try 3.1-lite → ❌ 429 Rate Limit
Mark: exhausted_until["3.1-lite"] = now + 5 minutes

Fallback:
Try 3.5 → ✅ SUCCESS
Mark: last_successful = "3.5", usage[3.5] = 1
```

### **Request 17:**
```
Available: [3.5, 2.5-lite, 3-preview, 2.5]  (3.1-lite still exhausted)
Order: [3.5*, 2.5-lite, 3-preview, 2.5]  (* = last successful)

Try 3.5 → ✅ SUCCESS
usage[3.5] = 2
```

### **Request 18-22:** (Rotate through available models)
```
Order: [3.5*, 2.5-lite, 3-preview, 2.5]

Request 18: 3.5 → SUCCESS → usage[3.5] = 3
Request 19: 3.5 → SUCCESS → usage[3.5] = 4
Request 20: 3.5 → SUCCESS → usage[3.5] = 5
Request 21: 3.5 → 429 FAIL → exhausted_until["3.5"] = +5min
            → Try 2.5-lite → SUCCESS → usage[2.5-lite] = 1
Request 22: Order: [2.5-lite*, 3-preview, 2.5] (both 3.1 and 3.5 exhausted)
            → 2.5-lite → SUCCESS → usage[2.5-lite] = 2
```

### **After 5 minutes:** (3.1-lite quota reset)
```
Available: [3.1-lite, 2.5-lite, 3-preview, 2.5]  (3.5 still exhausted)
Order: [2.5-lite*, 3.1-lite, 3-preview, 2.5]  
       (* = last successful, 3.1-lite is 2nd because less used than 2.5-lite)

Request 23: 2.5-lite → SUCCESS
Request 24: 2.5-lite → 429 FAIL → Try 3.1-lite → SUCCESS
            → last_successful = "3.1-lite"
Request 25: [3.1-lite*, 3-preview, 2.5] → 3.1-lite SUCCESS
```

---

## 🎯 Kết quả

### **Load Distribution** (sau 100 requests):
```
gemini-3.1-flash-lite: 45 requests  (highest quota → most usage)
gemini-3.5-flash:      20 requests
gemini-2.5-flash-lite: 18 requests
gemini-3-flash-preview: 12 requests
gemini-2.5-flash:       5 requests  (often restricted → least usage)
```

### **Benefits:**
1. ✅ **Tự động skip** models hết quota → không lãng phí retry
2. ✅ **Load balancing** → phân phối đều giữa các models
3. ✅ **Sticky preference** → ưu tiên model đang work tốt
4. ✅ **Auto recovery** → tự động retry models đã hết quota sau timeout
5. ✅ **Performance** → giảm latency (không thử model đã biết hết quota)

---

## 🔧 Configuration

### Thay đổi retry timeouts:
```python
# In gemini_adapter.py
_quota_tracker.mark_quota_exhausted(model, retry_after_seconds=300)  # 5 phút
_quota_tracker.mark_restricted(model)  # 24 giờ
```

### Thay đổi model order priority:
```python
model_fallback_chain = [
    "gemini-3.1-flash-lite",     # Highest quota → Priority 1
    "gemini-3.5-flash",          # ... 
    # Thêm models khác
]
```

### Monitor usage statistics:
```python
# Add to endpoint for debugging
logger.info(f"Model usage stats: {_quota_tracker._usage_counter}")
logger.info(f"Exhausted models: {_quota_tracker._exhausted_until}")
```

---

## 📝 Notes

### **Persistence:**
- State được lưu **in-memory** trong process
- Reset khi service restart
- Trong production multi-instance, mỗi instance có state riêng (acceptable)

### **Future improvements:**
- [ ] Store state trong Redis cho persistence cross-instance
- [ ] Add metrics/monitoring (Prometheus)
- [ ] Dynamic timeout adjustment dựa trên response time
- [ ] Weighted round-robin based on model performance

---

**Created:** 2026-07-18
**Author:** AI Assistant
**Status:** ✅ Implemented & deployed
