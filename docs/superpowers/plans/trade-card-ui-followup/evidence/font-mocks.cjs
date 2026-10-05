module.exports = new Proxy({}, { get(_target, url) {
  if (typeof url !== 'string') return undefined;
  const family = new URL(url).searchParams.get('family').split(':')[0].replace(/\+/g, ' ');
  return `/* latin */\n@font-face { font-family: '${family}'; font-style: normal; font-weight: 100 900; src: url(/usr/share/fonts/truetype/open-sans/OpenSans-Regular.ttf) format('truetype'); }`;
}});
