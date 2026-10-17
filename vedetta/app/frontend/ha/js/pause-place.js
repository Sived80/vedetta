// Where the pause menu goes: a pure function (nothing here touches the page, so a test can feed it any measure).
// The menu is centred on the round button of the Network card and is as wide as the room inside the card allows, so that it does not go past the right edge of the card
// (the button is about 118 px from it: a menu of 300 px, centred, went out by 30 px). Never wider than the maximum or than the window, never narrower than the minimum
// (then it may go past the card), and always inside the window (then it is not centred any more: the window wins).
export var PAUSE_MAX_W = 232, PAUSE_MIN_W = 184, PAUSE_EDGE = 8;

// button, card: {left, width} and {left, right} as the browser measures them; returns {left, width, originX} (originX: where the animation starts, from the left edge of the menu).
export function pausePlacement(button, card, winWidth) {
  const centre = button.left + button.width / 2;
  const room = 2 * (Math.min(centre - card.left, card.right - centre) - PAUSE_EDGE);
  const width = Math.min(PAUSE_MAX_W, winWidth - 2 * PAUSE_EDGE, Math.max(PAUSE_MIN_W, room));
  const left = Math.max(PAUSE_EDGE, Math.min(Math.round(centre - width / 2), winWidth - width - PAUSE_EDGE));
  return { left: left, width: width, originX: Math.round(centre - left) };
}
