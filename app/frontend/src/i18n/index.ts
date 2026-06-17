// Public surface of the i18n module.
export {LocaleProvider, useLocale, useT} from './LocaleContext';
export {translate} from './translate';
export {
  DEFAULT_LOCALE,
  LOCALES,
  dirOf,
  isRtl,
  type Locale,
  type TFunction,
  type TVars,
} from './types';
