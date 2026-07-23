const formatDate = (date: string | number | Date, withTime = false) => {
  const dateObj = new Date(date);

  if (withTime) {
    return Intl.DateTimeFormat(navigator.language, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(dateObj);
  }

  return Intl.DateTimeFormat(navigator.language).format(dateObj);
};

export default formatDate;
