const siteBase = document.querySelector('meta[name="site-base"]')?.content || '';
const header = document.querySelector('.site-header');
const updateHeader = () => header?.classList.toggle('is-scrolled', window.scrollY > 24);
window.addEventListener('scroll', updateHeader, {passive: true});
updateHeader();

const categories = {computers:'Компьютеры и моноблоки',laptops:'Ноутбуки и планшеты',displays:'Мониторы и интерактивные панели',printers:'Принтеры и МФУ',servers:'Серверы и сетевое оборудование',peripherals:'Периферия и ИБП',software:'Российское ПО',electronics:'Электроника и мультимедиа',appliances:'Бытовая техника',complex:'Комплексное оснащение',registry:'Техника из реестра Минпромторга'};
const params = new URLSearchParams(location.search);
const category = categories[params.get('category')] || '';
const services = ['Подбор оборудования','Подготовка ТЗ и спецификации','Коммерческое предложение','Комплексное оснащение','Доставка и установка','Гарантийное сопровождение'];
const serviceIndex = params.get('service');
const service = serviceIndex !== null && /^\d$/.test(serviceIndex) ? services[Number(serviceIndex)] || '' : '';
const emitEvent = (name, details={}) => window.dispatchEvent(new CustomEvent('ligus:conversion', {detail:{name,...details}}));

document.querySelectorAll('.request-form').forEach(form => {
  const file = form.elements.attachment;
  const error = form.querySelector('.form-error');
  const fileInfo = form.querySelector('.file-info');
  const submitButton = form.querySelector('button[type="submit"]');
  const submitLabel = submitButton.innerHTML;
  form.elements._next.value = `${location.origin}${siteBase}/thanks/`;
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
  form.addEventListener('submit', event => {
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
    HTMLFormElement.prototype.submit.call(form);
  });
  window.addEventListener('pageshow', () => {
    submitButton.disabled = false;
    submitButton.innerHTML = submitLabel;
  });
});
