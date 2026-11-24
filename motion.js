const stage = document.querySelector(".showcase");
const mouseMotion = matchMedia("(prefers-reduced-motion: no-preference) and (hover: hover) and (pointer: fine)");

function resetStage() {
  stage.style.removeProperty("--pitch");
  stage.style.removeProperty("--yaw");
}

stage.addEventListener("pointermove", (event) => {
  if (!mouseMotion.matches || event.pointerType !== "mouse") return;
  const bounds = stage.getBoundingClientRect();
  const x = (event.clientX - bounds.left) / bounds.width - 0.5;
  const y = (event.clientY - bounds.top) / bounds.height - 0.5;
  stage.style.setProperty("--pitch", `${-y * 7}deg`);
  stage.style.setProperty("--yaw", `${x * 9}deg`);
});
stage.addEventListener("pointerleave", resetStage);
mouseMotion.addEventListener("change", resetStage);

if ("IntersectionObserver" in window && "animate" in Element.prototype) {
  const revealMotion = matchMedia("(prefers-reduced-motion: no-preference)");
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      observer.unobserve(entry.target);
      if (!revealMotion.matches) continue;
      const animation = entry.target.animate(
        [{ opacity: 0.3, transform: "translateY(.75rem)" }, { opacity: 1, transform: "none" }],
        { duration: 510, easing: "cubic-bezier(.22, 1, .36, 1)" },
      );
      const finishOnPreferenceChange = () => animation.finish();
      revealMotion.addEventListener("change", finishOnPreferenceChange);
      animation.onfinish = () => revealMotion.removeEventListener("change", finishOnPreferenceChange);
    }
  }, { threshold: 0.2 });

  document.querySelectorAll(".steps li").forEach((step) => observer.observe(step));
}
