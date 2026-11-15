# -*- coding: utf-8 -*-
# by @嗷呜
import sys
import re
from pyquery import PyQuery as pq
sys.path.append('..')
from base.spider import Spider


class Spider(Spider):

    def init(self, extend=""):
        pass

    def getName(self):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass

    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'sec-ch-ua': '"Not/A)Brand";v="8", "Chromium";v="134", "Google Chrome";v="134"',
        'sec-ch-ua-platform': '"macOS"',
        'sec-fetch-dest': 'document',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
    }

    host = "https://4k-av.com"

    def homeContent(self, filter):
        data=self.getpq()
        result = {}
        classes = []
        for k in list(data('#category ul li').items())[:-1]:
            classes.append({
                'type_name': k.text(),
                'type_id': k('a').attr('href')
            })
        result['class'] = classes
        result['list'] = self.getlist(data('#MainContent_scrollul ul li'),'.poster span')
        return result

    def homeVideoContent(self):
        pass

    def categoryContent(self, tid, pg, filter, extend):
        # 站点无二级筛选：默认页是最新精选，page-N.html 却是最老片升序归档。
        # 第 1 页改为「默认页 + 热度页(?sort=hot) 合并去重」，再按
        # 年份(2026优先) > 热度页命中 > 收录ID 倒序，把刚上映/2026 新片与热门片排最前。
        try:
            p = max(1, int(str(pg).strip() or '1'))
        except Exception:
            p = 1
        base = str(tid or '').strip()
        if not base.endswith('/'):
            base += '/'
        sel = '#MainContent_newestlist .virow .NTMitem'
        try:
            pqobj = self.getpq(base if p == 1 else f'{base}page-{p}.html')
            lst = self.getlist(pqobj(sel), internal=True)
            maxpg = self._maxpage(pqobj)
            if p == 1:
                try:
                    hot = self._hot_best(base, sel)
                    hotids = set(v.get('vod_id') for v in hot if v.get('vod_id'))
                    seen, merged = set(), []
                    for v in lst + hot:
                        k = v.get('vod_id')
                        if not k or k in seen:
                            continue
                        seen.add(k)
                        if k in hotids:
                            v['_hot'] = 1
                        merged.append(v)
                    lst = merged
                except Exception:
                    pass
        except Exception:
            lst, maxpg = [], 0
        lst.sort(key=self._rank, reverse=True)
        result = {
            'list': [self._clean(v) for v in lst],
            'page': p,
            'pagecount': max(maxpg, p + 1, 1),
            'limit': max(len(lst), 24),
            'total': 0,
        }
        result['total'] = result['pagecount'] * result['limit']
        return result

    def detailContent(self, ids):
        data=self.getpq(ids[0])
        # 本页已抓取，顺手缓存播放直链：播放首集/本集时无需再请求详情页
        try:
            u0 = data('#MainContent_videowindow source').attr('src')
            if u0:
                self._cache_src(str(ids[0]), u0)
        except Exception:
            pass
        v=data('#videoinfo')
        vod = {
            'type_name': v('#MainContent_tags.tags a').text(),
            'vod_year': v('#MainContent_videodetail.videodetail a').text(),
            'vod_remarks': v('#MainContent_titleh12 h2').text(),
            'vod_content': v('p.cnline').text(),
            # 两条线路共用同一份选集：默认 1080P 最省带宽，需要真 4K 时手动切第二条
            'vod_play_from': '1080P流畅$$$4K超清',
            'vod_play_url': ''
        }
        vlist=data('#rtlist li')
        if vlist:
            c=[f"{i('span').text()}${i('a').attr('href')}" for i in list(vlist.items())[1:]]
            c.insert(0,f"{vlist.eq(0)('span').text()}${ids[0]}")
            play = '#'.join(c)
        else:
            play = f"{data('#tophead h1').text()}${ids[0]}"
        vod['vod_play_url'] = play + '$$$' + play
        return {'list':[vod]}

    def searchContent(self, key, quick, pg="1"):
        data=self.getpq(f"/s?k={key}")
        return {'list':self.getlist(data('#MainContent_newestlist .virow.search .NTMitem.Main'))}

    def playerContent(self, flag, id, vipFlags):
        # 直链优先取 detailContent 阶段缓存的；未命中才抓详情页并重试。
        # 不再退化成 parse=1 返回网页地址（端上会走 WebView 嗅探，极慢且易超时换源）。
        url = self._source_of(str(id))
        if not url:
            return {'parse': 0, 'url': '', 'header': self._play_headers()}
        # 选中「4K超清」线路时切到 /4K/ 档；部分影片无此档，探测失败自动回退 1080P
        if '4K' in str(flag).upper():
            alt = url.replace('/1080P/', '/4K/')
            if alt != url and self._is_m3u8(alt):
                url = alt
        return {'parse': 0, 'url': url, 'header': self._play_headers()}

    # ---- 播放链路加固：直链缓存 / 重试 / 最优请求头 / 4K 档探测 ----
    _src_cache = {}
    _src_order = []

    @classmethod
    def _cache_src(cls, key, url):
        cls._src_cache[key] = url
        try:
            cls._src_order.append(key)
            while len(cls._src_order) > 128:
                cls._src_cache.pop(cls._src_order.pop(0), None)
        except Exception:
            pass

    def _source_of(self, page):
        if page in self._src_cache:
            return self._src_cache[page]
        for _ in range(2):
            try:
                d = self.getpq(page)
                u = d('#MainContent_videowindow source').attr('src')
                if u:
                    self._cache_src(page, u)
                    return u
            except Exception:
                pass
        return ''

    def _play_headers(self):
        # 实测：不带 origin、referer 用主域时分片命中 Cloudflare HIT，
        # 带 www 的 origin/referer 反而容易 MISS 回源，速度掉一半。
        return {
            'referer': f'{self.host}/',
            'user-agent': self.headers.get('user-agent', ''),
        }

    def _is_m3u8(self, url):
        try:
            return '#EXTM3U' in self.fetch(url, headers=self.headers).text[:80]
        except Exception:
            return False

    def localProxy(self, param):
        pass

    def liveContent(self, url):
        pass

    # ---- 排序辅助（站点无二级筛选，改为按年份/热度/收录序自定义排序）----
    @staticmethod
    def _idnum(href):
        m = re.search(r'/(\d{5,7})-', str(href or ''))
        return int(m.group(1)) if m else 0

    @staticmethod
    def _yearnum(item, fallback=''):
        t = item('label[title="年份"]').text() or ''
        if not t:
            t = item('.resyear label').eq(1).text() or ''
        m = re.search(r'(?:19|20)\d{2}', t)
        if not m:
            m = re.search(r'(?:19|20)\d{2}', fallback or '')
        return int(m.group(0)) if m else 0

    @staticmethod
    def _clean(v):
        for k in ('_year', '_id', '_hot', '_res'):
            v.pop(k, None)
        return v

    @staticmethod
    def _rank(v):
        # 年份(2026 最前) > 热度页命中 > 收录ID(越大越新)
        return (v.get('_year', 0), v.get('_hot', 0), v.get('_id', 0))

    def _maxpage(self, pqobj):
        try:
            nums = [int(x) for x in re.findall(r'page-(\d+)\.html', str(pqobj))]
            return max(nums) if nums else 0
        except Exception:
            return 0

    def _hot_best(self, base, sel):
        # 热度页 ?sort=hot 抓 2 次，取「新片更多/收录更新」那版。
        # 站点 CDN 会随机返回旧版缓存，设备端直连通常命中新版，多取一次择优兜底。
        best, best_score = [], (-1, -1)
        for _ in range(2):
            try:
                cur = self.getlist(self.getpq(base + '?sort=hot')(sel), internal=True)
            except Exception:
                cur = []
            fresh = sum(1 for v in cur if v.get('_year', 0) >= 2026)
            maxid = max([v.get('_id', 0) for v in cur] or [0])
            if (fresh, maxid) > best_score:
                best_score, best = (fresh, maxid), cur
        return best

    def getlist(self, data, y='.resyear label[title="分辨率"]', internal=False):
        videos = []
        for i in data.items():
            ns = i('.title h2').text().split(' ')
            href = i('.title a').attr('href')
            extra = i(y).text() or ''
            year = self._yearnum(i, extra)
            v = {
                'vod_id': href,
                'vod_name': ns[0],
                'vod_pic': i('.poster img').attr('src'),
                'vod_remarks': ns[-1] if len(ns) > 1 else '',
                # 修正：原先误把「分辨率」填进 vod_year，这里填真实年份
                'vod_year': str(year) if year else extra,
            }
            if internal:
                v['_year'] = year
                v['_id'] = self._idnum(href)
                v['_res'] = i('label[title="分辨率"]').text() or ''
                v['_hot'] = 0
            videos.append(v)
        return videos

    def getpq(self, path=''):
        url=f"{self.host}{path}"
        data=self.fetch(url,headers=self.headers).text
        try:
            return pq(data)
        except Exception as e:
            print(f"{str(e)}")
            return pq(data.encode('utf-8'))



