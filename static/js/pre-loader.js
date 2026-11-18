function createBtnPreLoader(btn) {
    btn.disabled = true;
    btn.innerHTML = "Sending…";
}

function removeBtnPreLoader(btn, text) {
    btn.disabled = false;
    btn.innerHTML = text;
}

export function showBtnPreLoader(btn, status, text) {
    if (status) {
        createBtnPreLoader(btn);
    } else {
        removeBtnPreLoader(btn, text);
    }
}