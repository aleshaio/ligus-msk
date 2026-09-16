const siteBase = document.querySelector('meta[name="site-base"]')?.content || '';
const header = document.querySelector('.site-header');
const updateHeader = () => header?.classList.toggle('is-scrolled', window.scrollY > 24);
window.addEventListener('scroll', updateHeader, {passive: true});
updateHeader();

const mobileMenu = document.querySelector('.mobile-menu');
const menuToggles = document.querySelectorAll('.menu-toggle');
const mobileViewport = window.matchMedia('(max-width: 700px)');
let menuClosing;
let menuScrollY = 0;
let menuOpener;
const finishMenuClose = () => {
  clearTimeout(menuClosing);
  mobileMenu.close();
  mobileMenu.classList.remove('is-closing');
  document.documentElement.classList.remove('menu-open');
  menuToggles.forEach(button => button.setAttribute('aria-expanded', 'false'));
  window.scrollTo({top: menuScrollY, behavior: 'instant'});
  updateHeader();
  menuOpener?.focus({preventScroll: true});
};
const closeMenu = (immediate = false) => {
  if (!mobileMenu.open) return;
  if (immediate || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    finishMenuClose();
  } else {
    mobileMenu.classList.add('is-closing');
    menuClosing = setTimeout(finishMenuClose, 180);
  }
};
menuToggles.forEach(button => button.addEventListener('click', () => {
  clearTimeout(menuClosing);
  menuScrollY = window.scrollY;
  menuOpener = button;
  mobileMenu.classList.remove('is-closing');
  document.documentElement.classList.add('menu-open');
  menuToggles.forEach(toggle => toggle.setAttribute('aria-expanded', 'true'));
  mobileMenu.showModal();
}));
mobileMenu?.querySelector('.menu-close').addEventListener('click', () => closeMenu());
mobileMenu?.addEventListener('cancel', event => {
  event.preventDefault();
  closeMenu();
});
mobileMenu?.addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    event.preventDefault();
    closeMenu();
  }
});
mobileMenu?.addEventListener('click', event => {
  if (event.target.closest('a')) closeMenu(true);
});
mobileViewport.addEventListener('change', event => {
  if (!event.matches) closeMenu(true);
});
window.addEventListener('pageshow', () => {
  if (mobileMenu?.open) closeMenu(true);
});

const categories = {computers:'Компьютеры и моноблоки',laptops:'Ноутбуки и планшеты',displays:'Мониторы и интерактивные панели',printers:'Принтеры и МФУ',servers:'Серверы и сетевое оборудование',peripherals:'Периферия и ИБП',software:'Российское ПО',electronics:'Электроника и мультимедиа',appliances:'Бытовая техника',complex:'Комплексное оснащение',registry:'Техника из реестра Минпромторга'};
const params = new URLSearchParams(location.search);
const category = categories[params.get('category')] || '';
const services = ['Подбор оборудования','Подготовка ТЗ и спецификации','Коммерческое предложение','Комплексное оснащение','Доставка и установка','Гарантийное сопровождение'];
const serviceIndex = params.get('service');
const service = serviceIndex !== null && /^\d$/.test(serviceIndex) ? services[Number(serviceIndex)] || '' : '';
const emitEvent = (name, details={}) => window.dispatchEvent(new CustomEvent('ligus:conversion', {detail:{name,...details}}));

// No analytics or advertising providers are currently enabled. This dialog
// describes that state; it does not collect a blanket consent for future tools.
const cookieDialog = document.querySelector('#cookie-dialog');
document.querySelectorAll('.cookie-settings').forEach(link => {
  link.addEventListener('click', event => {
    if (!cookieDialog?.showModal) return;
    event.preventDefault();
    cookieDialog.showModal();
  });
});
cookieDialog?.querySelectorAll('.cookie-close, a').forEach(control => {
  control.addEventListener('click', () => cookieDialog.close());
});
cookieDialog?.addEventListener('click', event => {
  if (event.target !== cookieDialog) return;
  const rect = cookieDialog.getBoundingClientRect();
  if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) cookieDialog.close();
});

document.querySelectorAll('.request-form').forEach(form => {
  const file = form.elements.attachment;
  const error = form.querySelector('.form-error');
  const fileInfo = form.querySelector('.file-info');
  const submitButton = form.querySelector('button[type="submit"]');
  const submitLabel = submitButton.innerHTML;
  if (form.elements._next) form.elements._next.value = `${location.origin}${siteBase}/thanks/`;
  if(category || service) form.elements.comment.value = `Интересует: ${category || service}.\n`;
  function validateFile() {
    file.setCustomValidity('');
    const selected = file.files[0];
    if(!selected) { fileInfo.textContent=''; return true; }
    if(selected.size > 10 * 1024 * 1024) file.setCustomValidity('Файл больше 10 МБ. Отправьте его напрямую на tender@ligus-msk.ru или выберите файл меньшего размера.');
    if(!/\.(pdf|docx?|xlsx?|csv|txt)$/i.test(selected.name)) file.setCustomValidity('Поддерживаются PDF, DOC, DOCX, XLS, XLSX, CSV и TXT.');
    fileInfo.replaceChildren();
    const text = document.createElement('span');
    text.textContent = `${selected.name} · ${(selected.size/1024/1024).toFixed(2)} МБ`;
    const remove = document.createElement('button');
    remove.type='button'; remove.textContent='Убрать';
    remove.addEventListener('click',()=>{ file.value=''; file.setCustomValidity(''); fileInfo.replaceChildren(); error.textContent=''; file.focus(); });
    fileInfo.append(text,remove);
    error.textContent = file.validationMessage;
    return file.validity.valid;
  }
  file.addEventListener('change',validateFile);
  form.elements.phone.addEventListener('input',()=>form.elements.phone.setCustomValidity(''));
  let token = '';
  let sending = false;
  form.addEventListener('submit', async event => {
    if (sending) { event.preventDefault(); return; }
    event.preventDefault(); error.textContent='';
    const phone=form.elements.phone;
    const digits=phone.value.replace(/\D/g,'');
    phone.setCustomValidity(digits.length < 10 || digits.length > 15 ? 'Укажите телефон: от 10 до 15 цифр.' : '');
    validateFile();
    if(!form.checkValidity()) {
      const invalid=form.querySelector(':invalid');
      error.textContent = invalid?.validationMessage || 'Проверьте обязательные поля.';
      invalid?.focus(); form.reportValidity(); return;
    }
    if(form.elements._honey.value) return;
    submitButton.disabled = true;
    submitButton.textContent = 'Отправляем…';
    emitEvent('form_submit_started',{form:form.closest('.contact-section') ? 'home' : 'request'});
    if (form.dataset.provider !== 'smtp') {
      HTMLFormElement.prototype.submit.call(form);
      return;
    }
    sending = true;
    form.setAttribute('aria-busy', 'true');
    try {
      // The SMTP endpoint stays on this origin. Never fall back to a third party.
      const endpoint = new URL(form.action);
      if (endpoint.origin !== location.origin) throw new Error('Ошибка настройки формы. Свяжитесь с нами по телефону.');
      if (!token) {
        const tokenResponse = await fetch(endpoint, {credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(20000)});
        const result = await tokenResponse.json();
        if (!tokenResponse.ok || !result.token) throw new Error(result.message || 'Не удалось подготовить отправку. Повторите позже.');
        token = result.token;
      }
      const data = new FormData(form);
      data.set('token', token);
      const response = await fetch(endpoint, {method: 'POST', body: data, credentials: 'same-origin', signal: AbortSignal.timeout(65000)});
      const result = await response.json();
      if (!response.ok || result.ok !== true) {
        if (result.code === 'token_expired') token = '';
        if (result.field) form.elements.namedItem(result.field)?.focus();
        throw new Error(result.message || 'Не удалось подтвердить отправку. Свяжитесь с нами по телефону.');
      }
      emitEvent('form_submit_success');
      location.assign(`${siteBase}/thanks/`);
    } catch (failure) {
      error.textContent = failure instanceof TypeError || failure instanceof SyntaxError || failure.name === 'TimeoutError'
        ? 'Не удалось подтвердить отправку. Данные остались в форме. Проверьте соединение и повторите попытку или свяжитесь с нами по телефону.'
        : failure.message;
      error.setAttribute('tabindex', '-1');
      error.focus({preventScroll: true});
      submitButton.disabled = false;
      submitButton.innerHTML = submitLabel;
    } finally {
      sending = false;
      form.removeAttribute('aria-busy');
    }
  });
  window.addEventListener('pageshow', () => {
    submitButton.disabled = false;
    submitButton.innerHTML = submitLabel;
  });
});
