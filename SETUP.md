# NeuroTriage Bot v8 - Setup (Phase 2)

## Kya naya hai
| Cheez | Kaise kaam karta hai |
|---|---|
| **Raat 12 baje build** | `build.yml` roz 00:00 IST par chalta hai. 02:00 aur 04:00 IST par 2 **catch-up** runs: agar GitHub late start hua, busy tha ya build beech mein mar gayi, to ye bacha hua kaam poora karte hain. Video pehle se bani ho to ye seconds mein band ho jate hain. |
| **Dheere par pakka build** | Har bada step (research, script, voice, clips, render) ke baad checkpoint save hota hai. Build fail ho to 3 attempts tak wahin se resume (ElevenLabs credits dobara kharch nahi). Long video chapter-by-chapter segments mein render hota hai, mara hua run sirf adhura segment dobara banata hai. Timeout 5.5 ghante. |
| **Schedule ke hisab se publish** | Short default **10:00 IST**, Long **19:00 IST** (`PUBLISH_TIME_SHORT_IST` / `PUBLISH_TIME_LONG_IST`). YouTube (`publishAt`) aur Facebook (SCHEDULED) video ko raat mein hi le lete hain aur **khud** time par live karte hain. Instagram ka native schedule nahi hai, uska video `publish.yml` time par post karta hai. |
| **Long video (16:9)** | 1920x1080, 6 chapters, Hinglish ElevenLabs narration, landscape stock clips, **3D chapter cards** (ghoomta neuron sphere + perspective floor), stat cards (script mein "73 percent" jaise number ho to), end card, progress bar, thumbnail, YouTube chapters description mein. |
| **Naye caption styles** | `pop`, `box`, `karaoke`, `bounce`, `glow` (Short) aur `clean` (Long). `CAPTION_STYLE: auto` roz badalta hai. |

## Files
`bot.py`, `scheduler.py`, `publish_due.py`, `watchdog.py`, `ckpt.py`, `long_render.py`, `motion_graphics.py`, `caption_styles.py`, `gfx.py`, `publisher.py`, `eleven_voice.py`, `virality.py`, `requirements.txt`, `queue/` (folder, rehne do), `assets/` (pehle jaisa: `neurotriage_splash.json`, `logo.png`, `music.mp3`, `font.ttf`), `.github/workflows/build.yml`, `.github/workflows/publish.yml`.

**Purani `.github/workflows/daily.yml` delete karo.** Nahi to roz do video banenge.

## Secrets
Phase 1 jaise hi, koi naya secret nahi. (`GITHUB_TOKEN` GitHub khud deta hai.) Naam copy-paste ke liye:
`GROQ_API_KEY`, `GROQ_API_KEY_2`, `GEMINI_API_KEY` (+`_2.._4`), `ELEVEN_API_KEY_1` ... `ELEVEN_API_KEY_10`, `ELEVEN_VOICE_IDS`, `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `YT_API_KEY`, `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`, `IG_USER_ID`, `META_ACCESS_TOKEN`, `FB_PAGE_ID`, `FB_PAGE_TOKEN`.

Repo Settings -> Actions -> General -> Workflow permissions: **Read and write permissions** ON.

## Pehli baar safe chalane ka tareeka
1. Sirf YouTube + ElevenLabs + Pexels secrets, `PRIVACY: private`. Actions -> **Midnight Build** -> Run workflow (`publish_asap` = 1). Output: Artifacts mein `queue-<date>-short`.
2. 2-3 raat chalne do. Check: video theek, `queue/` mein manifest commit hua, 10:00 par `publish.yml` chala.
3. Long video test: Run workflow, `force_long` = 1. Pehla long render 30-90 min le sakta hai (GitHub runner par), ye normal hai.
4. Phir `PRIVACY: public` (build.yml mein), tab YouTube `publishAt` se khud live hoga.
5. Sabse last Meta tokens. **Instagram/Facebook par private option nahi hai**, `PRIVACY: private` ho tab bhi Meta par video schedule/post ho jayegi. Meta tokens tabhi daalo jab YouTube videos pasand aa jayein.

## Time badalna ho to
`build.yml` ke `PUBLISH_TIME_SHORT_IST` / `PUBLISH_TIME_LONG_IST` badlo **aur** `publish.yml` ke cron windows bhi (UTC = IST - 5:30). Build ka time `build.yml` ke `cron: "30 18 * * *"` se (18:30 UTC = 00:00 IST).

## Settings (build.yml `env:`)
`RENDER_PRESET` (Short encode, `slow`), `LONG_PRESET`, `LONG_FPS` (24), `LONG_RENDER` (off = sirf script kit), `LONG_VISION` (off = clip chunav bina Gemini ke, kam API use), `CAPTION_STYLE`, `NATIVE_SCHEDULE` (off = YouTube/Facebook bhi publish time par post honge, build time par nahi), `MIN_LEAD_MIN` (25).

## ElevenLabs credits
Short ~700 characters. Long (7 min) ~6-7 hazaar characters hafte mein ek baar. 10 free keys ka total mahine ka buffer kaafi hai, par long ke din balance check hota hai aur sab keys fail hon to English + edge-tts fallback chalta hai (captions bhi English).

## Jo maine asli duniya mein test NAHI kiya (pehle private par dekho)
- Asli YouTube `publishAt`, Facebook `SCHEDULED`, Instagram upload, artifact download (GitHub API) - sirf mock se test hue.
- Asli ElevenLabs, Pexels/Pixabay clips, aur Lottie splash (`neurotriage_splash.json` mere paas nahi tha, test mein nakli splash tha).
- Asli runner par render ka time. Mere 1-core test mein 1080p 3D frame ~0.2 sec/frame aaya, GitHub runner par 7 min ka video isse tez ya similar hona chahiye.
- GitHub cron kabhi 10-30 min late chalta hai. YouTube/Facebook is se bachte hain (unka schedule unke server par hai), sirf Instagram late ho sakta hai.

## Offline test chalana
`python tests/test_phase2.py` (poora flow: build -> queue -> publish -> idempotent) aur `python tests/test_resume.py` (render beech mein mare to resume).


## Round 3 - kaise chalana (Actions -> Midnight Build -> Run workflow)
| Tum kya chahte ho | Inputs |
|---|---|
| Roz ka auto | kuch nahi. Sirf **Short** banta hai (10:00 IST). |
| **Long video** | Actions -> **Long Video (on demand)** -> Run workflow. `publish_time_ist` khali = 19:00 IST. (Round 4: alag workflow, video_type input hat gaya) |
| Long video **turant live** | Long Video workflow, `publish_when` = `now` (PUBLIC ho jaati hai, build khatam hote hi upload) |
| Apne time par | `publish_time_ist` = `17:30` (aaj ka time nikal gaya ho to agle din) |
| Script badalni hai | `unlock_script` = `1` (sirf tab nayi script banti hai) |

- **Script Lock:** pehli audited script lock ho jaati hai. Retry, resume, doosra AI (Gemini <-> Groq) - koi use badal nahi sakta. Badli hui script `state/<date>_short.json` ke `pending` mein jaati hai, apply nahi hoti.
- **AI memory:** har AI call ke aage project state jaata hai (final topic, verified facts, script locked, pehle AI ne kya kiya). `state/` repo mein commit hota hai (kaun sa AI, kaun sa key-LABEL; key ki value kabhi nahi).
- **Research:** PubMed + Wikipedia se check. Jis fact mein number hai aur wo number evidence mein nahi milta, wo hata diya jaata hai. Description mein `Sources:` line aati hai.
- **Logo:** chhota circle, upar-right (reel), corner (long), end card, thumbnail. `LOGO: "off"` se band. Upar ka loading bar hata diya.
- Purana rhythm (din 7 = short + long) wapas chahiye: `AUTO_LONG: "on"`.

## Round 4 - speed
- Short aur Long ab alag workflows (`build.yml`, `build_long.yml`), ek hi concurrency group: ek chal raha ho to doosra intezaar karta hai, saath nahi chalte, kuch cancel nahi hota.
- Footage: search parallel + 7 din cache, vision 4 scenes ek call mein, download parallel. Retry/resume par wahi clip dobara download nahi hoti.
- Kal ki clips 14 din tak dobara nahi aati (`FOOTAGE_NO_REPEAT_DAYS`).
