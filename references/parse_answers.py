#!/usr/bin/env python3
"""Parse raw answers text into structured JSON."""
import json
import re

KNOWN_CATEGORIES = [
    "科技与创新", "商业与经济", "历史与文化", "文学与艺术",
    "运动与娱乐", "职业与发展", "学习与教育", "健康与生命",
    "健康与生活", "自然与农业", "旅游与交通",
]
SECTION_HEADERS = {"听问天下", "书海遨游", "听闻天下"}
SKIP_NOTES = {"阅读即可", "太长了不划算", "无题目，听完就算一篇有效", "也是阅读即可"}

def looks_like_answer_line(line):
    line = line.strip()
    if not line:
        return False
    letters = re.sub(r'\s+', '', line).replace('?', '').replace('(', '').replace(')', '')
    if re.match(r'^[A-D]{2,}$', letters):
        return True
    if re.match(r'^\(\d+\)', line):
        return True
    if re.search(r'\(\d+\)\s*[A-Za-z]', line):
        return True
    # Word-fill answers: lowercase words separated by multiple spaces, or containing numbers/percent
    # Example: "personal freedom of mobility   75 percent    his vision and leadership"
    if re.search(r'\b\d+\s+(percent|per cent)\b', line, re.IGNORECASE):
        return True
    if re.match(r'^[a-z]', line) and len(line.split()) >= 5:
        return True
    return False

def looks_like_subcategory(line):
    return line.strip() in KNOWN_CATEGORIES

def looks_like_section(line):
    return line.strip() in SECTION_HEADERS

def looks_like_title(text):
    line = text.strip()
    if not line or len(line) < 6:
        return False
    if line in SKIP_NOTES:
        return False
    if looks_like_subcategory(line) or looks_like_section(line):
        return False
    if re.match(r'^\(\d+\)', line):
        return False
    if re.search(r'\(\d+\)\s*[A-Z]', line):
        return False
    if re.match(r'^\s*[A-D]{3,}', line):
        return False
    if re.match(r'^\s*[A-D]{2,}\s*[A-D\s]*\(\d+\)', line):
        return False
    letters = re.sub(r'\s+', '', line)
    if re.match(r'^[A-D?]{2,}$', letters):
        return False
    if re.match(r'^[一-鿿\s，。！？、；：]+$', line):
        return False
    # Lines starting with lowercase are likely not titles (answer continuations)
    first_alpha = next((c for c in line if c.isascii() and c.isalpha()), None)
    if first_alpha and first_alpha.islower():
        return False
    # Lines with numeric tokens (percent, numbers) mixed with words are likely word-fill answers
    if re.search(r'\b\d+\s+(percent|per cent|%)', line, re.IGNORECASE):
        return False
    alpha = sum(1 for c in line if c.isascii() and c.isalpha())
    return alpha >= 6

def parse_answers(text):
    text = text.strip()
    result = {"raw": text}

    # Extract fill-in-the-blank: (1)answer or (1) A-answer
    fills = re.findall(r'\((\d+)\)\s*([A-Za-z一-鿿]+(?:[-\s]+[A-Za-z一-鿿]+)*)', text)
    fill_parts = [{"index": int(idx), "answer": ans.strip()} for idx, ans in fills]

    # Extract multiple-choice letters: remove fill-in parts first, then get all A-D letters
    mc_text = re.sub(r'\(\d+\)\s*[A-Za-z一-鿿]+(?:[-\s]+[A-Za-z一-鿿]+)*', '', text)
    # Collect individual A-D letters (handles both "A B C" and "ABC" formats)
    letters = re.findall(r'[A-D?]', mc_text)

    if letters and len(letters) >= 2 and fill_parts:
        result["format"] = "letter_and_fill"
        result["letters"] = letters
        result["fill_in_blank"] = fill_parts
    elif fill_parts:
        result["format"] = "fill_in_blank"
        result["fill_in_blank"] = fill_parts
    elif letters and len(letters) >= 2:
        result["format"] = "letters"
        result["letters"] = letters
    else:
        result["format"] = "unknown"
    return result

def split_title_answer(s):
    s = s.strip()
    # Title……BCBCD
    m = re.match(r'^(.+?)\s*[.…]{2,}\s*([A-D]{2,})$', s)
    if m: return m.group(1).strip(), m.group(2).strip()
    # Title + skip note
    for note in SKIP_NOTES:
        if s.endswith(note) and len(s) > len(note):
            return s[:-len(note)].strip().rstrip('…。，,. '), None
    # Title   BDBBA (2+ spaces separation)
    m = re.match(r'^(.+?)\s{2,}([A-D\s]{2,}(?:\s*\(?\d+\)?\s*[A-Za-z]+)*)$', s)
    if m:
        t, a = m.group(1).strip(), m.group(2).strip()
        # Title must not be pure uppercase letters
        if re.match(r'^[A-D\s?]+$', re.sub(r'\s+', '', t)):
            return None, None
        if re.match(r'^[A-D\s]+$', re.sub(r'\s+', '', a)):
            return t, a
    # TitleADBAB (no space, title must have lowercase)
    m = re.match(r'^(.+?\S)([A-D]{2,})\s*$', s)
    if m:
        t, a = m.group(1).strip(), m.group(2).strip()
        if len(t) >= 3 and len(a) >= 2 and re.search(r'[a-z]', t):
            return t, a
    # Title(1)A (2)B ... title has lowercase, doesn't start with (
    m = re.match(r'^(\S.+?\S)\s*\(\d+\).+$', s)
    if m and not re.match(r'^\(\d+\)', s) and re.search(r'\(\d+\)\s*[A-Z]', s):
        t = m.group(1).strip()
        if len(t) >= 2 and not t.startswith('(') and re.search(r'[a-z]', t):
            idx = s.index('(')
            return t, s[idx:]
    return None, None

def main():
    with open("references/answers", "r", encoding="utf-8") as f:
        lines = f.readlines()

    current_section, current_category = None, None
    articles = []
    cur = None
    pending = []

    def flush():
        nonlocal cur, pending
        if not cur: return
        if pending:
            combined = ' '.join(pending)
            if cur["answers"] and cur["answers"]["format"] != "unknown":
                combined = cur["answers"]["raw"] + ' | ' + combined
            cur["answers"] = parse_answers(combined)
            pending = []
        articles.append(cur)
        cur = None

    def mkart(title, cat, ans=None, skip=None):
        return {
            "title": title,
            "category": cat or "未分类",
            "type": "listening" if (current_section and "听" in current_section) else "reading",
            "answers": parse_answers(ans) if ans else None,
            "skip_reason": skip
        }

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line: continue

        if looks_like_section(line):
            flush(); current_section = line; current_category = None; continue
        if looks_like_subcategory(line):
            flush(); current_category = line; continue

        t, a = split_title_answer(line)
        if t is not None:
            flush()
            articles.append(mkart(t, current_category,
                                  ans=a, skip="（阅读即可）" if (a is None and "阅读即可" in line) else None))
            continue

        if line in SKIP_NOTES:
            if cur: cur["skip_reason"] = line; flush()
            continue

        if looks_like_title(line):
            flush()
            cur = mkart(line, current_category)
            continue

        if looks_like_answer_line(line):
            buf = [line]
            while i < len(lines):
                nl = lines[i].strip()
                if not nl: i += 1; continue
                if looks_like_title(nl) or looks_like_subcategory(nl) or looks_like_section(nl): break
                # Also stop if nl looks like a new article title
                t2, _ = split_title_answer(nl)
                if t2 and len(t2) > 5: break
                buf.append(nl); i += 1
            combined = ' '.join(buf)
            if cur:
                pending.append(combined)
            else:
                # Orphan — attach to last unanswered article
                attached = False
                for art in reversed(articles):
                    if art["answers"] is None and art.get("skip_reason") is None:
                        art["answers"] = parse_answers(combined)
                        attached = True
                        break
                if not attached:
                    articles.append(mkart(f"(orphan) {combined[:60]}", current_category, ans=combined))
            continue

    flush()

    # Remove any orphan entries that got merged into previous articles
    articles = [a for a in articles if not a["title"].startswith("(orphan)")]

    output = {
        "description": "慧学外语阅读题目答案库（来自论坛整理）",
        "article_count": len(articles),
        "articles": articles
    }

    by_cat, unans = {}, []
    for a in articles:
        by_cat[a["category"]] = by_cat.get(a["category"], 0) + 1
        if a["answers"] is None and a.get("skip_reason") is None:
            unans.append(a)

    print("=== Category stats ===")
    for k, v in sorted(by_cat.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
    print(f"\nUnanswered: {len(unans)}")
    for a in unans:
        print(f"  [{a['category']}] {a['title'][:80]}")
    print(f"\nTotal: {len(articles)}")

    with open("references/answers.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("Written to references/answers.json")

if __name__ == "__main__":
    main()
