/* ══════════════════════════════════════════════════════
   ERUPTION — Full Page JS
   Act 1: Lenis · Canvas · Frame Engine
           Left Panel Animation · Heat Meter
   Act 2: Landing Section Reveals · Landing Counters
          Canvas + Left Panel Fade-Out
══════════════════════════════════════════════════════ */

(function () {
  "use strict";

  /* ────────────────────────────────────────
     CONSTANTS
  ──────────────────────────────────────── */
  const FRAME_COUNT     = 241;
  const FRAME_SPEED     = 2.0;
  const IMAGE_SCALE     = 0.88;
  const FRAMES_DIR      = "frames/";
  const FRAME_EXT       = ".jpg";
  const PRELOAD_FIRST   = 10;
  const BG_SAMPLE_EVERY = 20;
  const MAX_SHU         = 4200000;

  /* ────────────────────────────────────────
     ELEMENTS
  ──────────────────────────────────────── */
  const loader        = document.getElementById("loader");
  const loaderBar     = document.getElementById("loader-bar");
  const loaderPercent = document.getElementById("loader-percent");
  const canvas        = document.getElementById("canvas");
  const ctx           = canvas.getContext("2d");
  const canvasWrap    = document.getElementById("canvasWrap");
  const leftPanel     = document.getElementById("leftPanel");
  const scrollCont    = document.getElementById("scroll-container");
  const heatBarFill   = document.getElementById("heatBarFill");
  const heatValue     = document.getElementById("heatValue");
  const siteHeader    = document.getElementById("siteHeader");
  const canvasExit    = document.getElementById("canvasExitTrigger");

  /* ────────────────────────────────────────
     STATE
  ──────────────────────────────────────── */
  const frames      = new Array(FRAME_COUNT + 1);
  let loadedCount   = 0;
  let currentFrame  = 0;
  let bgColor       = "#000000";
  let sampledFrame  = -1;

  /* ══════════════════════════════════════
     1. PRELOADER
  ══════════════════════════════════════ */
  function padFrame(n) {
    return String(n).padStart(4, "0");
  }

  function frameSrc(n) {
    return `${FRAMES_DIR}frame_${padFrame(n)}${FRAME_EXT}`;
  }

  function updateLoaderUI(loaded, total) {
    const pct = Math.round((loaded / total) * 100);
    loaderBar.style.width = pct + "%";
    loaderPercent.textContent = String(pct).padStart(3, "0") + "%";
  }

  function loadFrame(index) {
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        frames[index] = img;
        loadedCount++;
        updateLoaderUI(loadedCount, FRAME_COUNT);
        resolve();
      };
      img.onerror = () => {
        loadedCount++;
        updateLoaderUI(loadedCount, FRAME_COUNT);
        resolve();
      };
      img.src = frameSrc(index);
    });
  }

  async function preloadFirstBatch() {
    const p = [];
    for (let i = 1; i <= Math.min(PRELOAD_FIRST, FRAME_COUNT); i++) p.push(loadFrame(i));
    await Promise.all(p);
  }

  function preloadRemaining() {
    const p = [];
    for (let i = PRELOAD_FIRST + 1; i <= FRAME_COUNT; i++) p.push(loadFrame(i));
    return Promise.all(p); // fire and forget from caller
  }

  function hideLoader() {
    loader.classList.add("hidden");
    setTimeout(() => { loader.style.display = "none"; }, 900);
  }

  async function initPreloader() {
    await preloadFirstBatch();
    resizeCanvas();
    drawFrame(1);
    hideLoader();
    siteHeader.classList.add("visible");
    // Reveal canvas (starts at opacity 0 in CSS)
    gsap.to(canvasWrap, { opacity: 1, duration: 1.0, ease: "power2.out", delay: 0.2 });
    animateLeftPanel();
    preloadRemaining(); // background
    initAnimations();
  }

  /* ══════════════════════════════════════
     2. CANVAS — padded-cover (60vw panel)
  ══════════════════════════════════════ */
  function resizeCanvas() {
    const dpr = window.devicePixelRatio || 1;
    const cw  = canvasWrap.offsetWidth;
    const ch  = canvasWrap.offsetHeight;
    canvas.width  = cw * dpr;
    canvas.height = ch * dpr;
    ctx.scale(dpr, dpr);
    canvas.style.width  = cw + "px";
    canvas.style.height = ch + "px";
  }

  function sampleBgColor(img) {
    try {
      const off = document.createElement("canvas");
      off.width  = img.naturalWidth;
      off.height = img.naturalHeight;
      const oc = off.getContext("2d");
      oc.drawImage(img, 0, 0);
      const w = img.naturalWidth, h = img.naturalHeight;
      const corners = [
        oc.getImageData(0, 0, 1, 1).data,
        oc.getImageData(w - 1, 0, 1, 1).data,
        oc.getImageData(0, h - 1, 1, 1).data,
        oc.getImageData(w - 1, h - 1, 1, 1).data,
      ];
      const r = Math.round(corners.reduce((s, c) => s + c[0], 0) / 4);
      const g = Math.round(corners.reduce((s, c) => s + c[1], 0) / 4);
      const b = Math.round(corners.reduce((s, c) => s + c[2], 0) / 4);
      bgColor = `rgb(${r},${g},${b})`;
    } catch (e) { bgColor = "#000"; }
  }

  function drawFrame(index) {
    const img = frames[index];
    if (!img) return;

    const cw = canvasWrap.offsetWidth;
    const ch = canvasWrap.offsetHeight;
    const iw = img.naturalWidth;
    const ih = img.naturalHeight;

    if (index % BG_SAMPLE_EVERY === 0 && index !== sampledFrame) {
      sampledFrame = index;
      sampleBgColor(img);
    }

    const scale = Math.max(cw / iw, ch / ih) * IMAGE_SCALE;
    const dw = iw * scale, dh = ih * scale;
    const dx = (cw - dw) / 2, dy = (ch - dh) / 2;

    ctx.fillStyle = bgColor;
    ctx.fillRect(0, 0, cw, ch);
    ctx.drawImage(img, dx, dy, dw, dh);
  }

  window.addEventListener("resize", () => { resizeCanvas(); drawFrame(currentFrame); });

  /* ══════════════════════════════════════
     3. LEFT PANEL ANIMATION (on load)
  ══════════════════════════════════════ */
  function animateLeftPanel() {
    const eyebrow   = document.querySelector(".lp-eyebrow");
    const words     = document.querySelectorAll(".lp-word");
    const sub       = document.querySelector(".lp-sub");
    const btns      = document.querySelector(".lp-btns");
    const scrollCue = document.querySelector(".lp-scroll-cue");
    const heatMeter = document.getElementById("heatMeter");

    const tl = gsap.timeline({ defaults: { ease: "power3.out" } });

    if (eyebrow)           tl.from(eyebrow,   { opacity: 0, y: 15, duration: 0.7 }, 0.4);
    if (words.length)      tl.from(words,     { opacity: 0, y: 45, stagger: 0.13, duration: 1.0 }, 0.6);
    if (sub)               tl.from(sub,       { opacity: 0, y: 20, duration: 0.7 }, 1.15);
    if (btns)              tl.from(btns,      { opacity: 0, y: 20, duration: 0.7 }, 1.3);
    if (scrollCue)         tl.from(scrollCue, { opacity: 0, duration: 0.6 }, 1.6);
    if (heatMeter)         tl.from(heatMeter, { opacity: 0, duration: 0.6 }, 1.7);
  }

  /* ══════════════════════════════════════
     4. MAIN ANIMATION INIT
  ══════════════════════════════════════ */
  function initAnimations() {
    gsap.registerPlugin(ScrollTrigger);

    // ── Lenis ────────────────────────────
    const lenis = new Lenis({
      duration: 1.2,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
      smoothWheel: true,
    });
    lenis.on("scroll", ScrollTrigger.update);
    gsap.ticker.add((time) => lenis.raf(time * 1000));
    gsap.ticker.lagSmoothing(0);

    // ── Header state ─────────────────────
    ScrollTrigger.create({
      trigger: scrollCont,
      start: "top 30%",
      onEnter:     () => siteHeader.classList.add("scrolled"),
      onLeaveBack: () => siteHeader.classList.remove("scrolled"),
    });

    // ── Frame-to-scroll binding ──────────
    ScrollTrigger.create({
      trigger: scrollCont,
      start: "top top",
      end: "bottom bottom",
      scrub: true,
      onUpdate: (self) => {
        const acc   = Math.min(self.progress * FRAME_SPEED, 1);
        const index = Math.min(Math.floor(acc * FRAME_COUNT) + 1, FRAME_COUNT);
        if (index !== currentFrame) {
          currentFrame = index;
          requestAnimationFrame(() => drawFrame(currentFrame));
        }

        // Live heat meter in left panel
        const shu = Math.round(self.progress * MAX_SHU);
        if (heatBarFill) heatBarFill.style.width = (self.progress * 100) + "%";
        if (heatValue) heatValue.textContent = shu >= 1000000
          ? (shu / 1000000).toFixed(1) + "M SHU"
          : shu >= 1000
          ? (shu / 1000).toFixed(0) + "K SHU"
          : shu + " SHU";
      },
    });

    // ── Canvas + Left Panel fade-out on landing entry ──
    initCanvasFadeOut();

    // ── Landing section reveals ──────────
    initLandingReveals();
  }

  /* ══════════════════════════════════════
     5. CANVAS + LEFT PANEL FADE-OUT
  ══════════════════════════════════════ */
  function initCanvasFadeOut() {
    ScrollTrigger.create({
      trigger: canvasExit,
      start: "top 80%",
      end: "top 20%",
      scrub: true,
      onUpdate: (self) => {
        const op = 1 - self.progress;
        canvasWrap.style.opacity = op;
        leftPanel.style.opacity  = op;
      },
    });
  }

  /* ══════════════════════════════════════
     6. LANDING SECTION REVEALS (Act 2)
  ══════════════════════════════════════ */
  function initLandingReveals() {
    // ── Hero — fade-up stagger ────────────
    const heroSection = document.getElementById("landing-hero");
    if (heroSection) {
      const heroEls = [
        heroSection.querySelector(".landing-label"),
        heroSection.querySelector(".landing-hero-heading"),
        heroSection.querySelector(".lava-rule"),
        heroSection.querySelector(".landing-hero-sub"),
        heroSection.querySelector(".landing-hero-btns"),
      ].filter(Boolean);

      if (heroEls.length) {
        gsap.from(heroEls, {
          y: 50, opacity: 0,
          stagger: 0.14,
          duration: 1.0,
          ease: "power3.out",
          scrollTrigger: { trigger: heroSection, start: "top 70%", toggleActions: "play none none none" },
        });
      }
    }

    // ── Features header ──────────────────
    const featHeader = document.querySelectorAll(".features-header .landing-label, .features-title");
    if (featHeader.length) {
      gsap.from(featHeader, {
        y: 40, opacity: 0,
        stagger: 0.12,
        duration: 0.9,
        ease: "power3.out",
        scrollTrigger: { trigger: ".features-header", start: "top 80%", toggleActions: "play none none none" },
      });
    }

    // ── Feature rows — alternating slide direction ──
    document.querySelectorAll(".feature-row").forEach((row, i) => {
      gsap.from(row, {
        x: i % 2 === 0 ? -70 : 70,
        opacity: 0,
        duration: 1.0,
        ease: "power3.out",
        scrollTrigger: { trigger: row, start: "top 78%", toggleActions: "play none none none" },
      });
    });

    // ── Stats bar — stagger-up ────────────
    gsap.from(".lp-stat", {
      y: 40, opacity: 0,
      stagger: 0.12,
      duration: 0.9,
      ease: "power3.out",
      scrollTrigger: { trigger: "#landing-stats", start: "top 75%", toggleActions: "play none none none" },
    });

    // ── Landing counters ─────────────────
    document.querySelectorAll(".lp-stat-num").forEach((el) => {
      const decimals = parseInt(el.dataset.lpDecimals || "0");
      const suffix   = el.dataset.lpSuffix || "";
      const snap     = decimals === 0 ? 1 : Math.pow(10, -decimals);

      gsap.from(el, {
        textContent: 0,
        duration: 2.2,
        ease: "power1.out",
        snap: { textContent: snap },
        scrollTrigger: {
          trigger: el.closest(".lp-stat"),
          start: "top 85%",
          toggleActions: "play none none none",
        },
        onUpdate() {
          const val = parseFloat(el.textContent);
          el.textContent = decimals > 0
            ? val.toFixed(decimals) + suffix
            : Math.round(val) + suffix;
        },
      });
    });

    // ── Final CTA — scale-up entrance ────
    const ctaSection = document.getElementById("landing-cta");
    if (ctaSection) {
      const ctaLabel   = ctaSection.querySelector(".landing-label");
      const ctaHeading = ctaSection.querySelector(".landing-cta-heading");
      const ctaSub     = ctaSection.querySelector(".landing-cta-sub");
      const ctaBtns    = ctaSection.querySelector(".landing-cta-btns");

      if (ctaLabel) {
        gsap.from(ctaLabel, {
          opacity: 0, y: 12, duration: 0.7, ease: "power2.out",
          scrollTrigger: { trigger: ctaSection, start: "top 75%", toggleActions: "play none none none" },
        });
      }
      if (ctaHeading) {
        gsap.from(ctaHeading, {
          scale: 0.92, opacity: 0, duration: 1.1, ease: "power3.out", delay: 0.1,
          scrollTrigger: { trigger: ctaSection, start: "top 75%", toggleActions: "play none none none" },
        });
      }
      const ctaBottomEls = [ctaSub, ctaBtns].filter(Boolean);
      if (ctaBottomEls.length) {
        gsap.from(ctaBottomEls, {
          y: 30, opacity: 0, stagger: 0.14, duration: 0.9, ease: "power3.out", delay: 0.2,
          scrollTrigger: { trigger: ctaSection, start: "top 75%", toggleActions: "play none none none" },
        });
      }
    }

    // ── Heat levels bar + labels ─────────
    const heatLevels = document.querySelector(".heat-levels");
    const heatLabels = document.querySelector(".heat-level-labels");

    if (heatLevels) {
      gsap.from(heatLevels, {
        scaleX: 0, opacity: 0, duration: 1.2, ease: "power4.out", delay: 0.5,
        transformOrigin: "left center",
        scrollTrigger: { trigger: heatLevels, start: "top 85%", toggleActions: "play none none none" },
      });
    }
    if (heatLabels) {
      gsap.from(heatLabels, {
        opacity: 0, duration: 0.6, delay: 0.9,
        scrollTrigger: { trigger: heatLabels, start: "top 85%", toggleActions: "play none none none" },
      });
    }
  }

  /* ══════════════════════════════════════
     BOOT
  ══════════════════════════════════════ */
  window.addEventListener("DOMContentLoaded", () => {
    resizeCanvas();
    initPreloader();
  });

})();
