// Delegate to the shared host API so every plugin bundle observes the same
// router instance. Importing ../../kernel/router directly would inline a
// separate copy into each bundle and break cross-plugin navigation.
export {
  notFound,
  redirect,
  useParams,
  usePathname,
  useRouter,
  useSearchParams,
} from '@app/host';
