// One-shot database bootstrap for the local docker-compose stack.
//
// The **connection string is the single source of truth**: this script parses
// `MONGODB_URI` (the same value python-backend uses) to discover the database,
// the application user and its password. There are no separate MONGO_APP_* vars
// to drift out of sync.
//
// Credentials are created through a root connection string (`MONGO_ROOT_URI`,
// used by mongosh), because a user cannot create itself.
//
// Collection validators and indexes are still owned by python-backend
// (`store.ensure_schema`) — do not pre-create those collections here, or the
// validators would be skipped.

function parseMongoUri(uri) {
  const match = /^mongodb(\+srv)?:\/\/(?:([^:@/]+)(?::([^@/]*))?@)?([^/?]+)(?:\/([^?]*))?(?:\?(.*))?$/.exec(
    (uri || "").trim(),
  );
  if (!match) {
    throw new Error(`MONGODB_URI is not a valid mongodb:// or mongodb+srv:// string: ${uri}`);
  }
  const [, srv, user, pass, host, pathname, query] = match;
  return {
    srv: Boolean(srv),
    user: user ? decodeURIComponent(user) : "",
    password: pass !== undefined ? decodeURIComponent(pass) : "",
    host,
    database: pathname ? decodeURIComponent(pathname) : "",
    params: new URLSearchParams(query || ""),
  };
}

const uri = process.env.MONGODB_URI;
if (!uri) {
  throw new Error("MONGODB_URI is not set");
}

const parsed = parseMongoUri(uri);
const dbName = parsed.database || "lirify";
const appDb = db.getSiblingDB(dbName);

print(`target host=${parsed.host} database=${dbName} user=${parsed.user || "(none)"}`);

if (!parsed.user) {
  print("MONGODB_URI has no credentials; skipping user creation (no-auth local setup)");
} else if (!parsed.password) {
  throw new Error("MONGODB_URI contains a user but no password");
} else {
  try {
    appDb.createUser({
      user: parsed.user,
      pwd: parsed.password,
      roles: [
        { role: "readWrite", db: dbName },
        { role: "dbAdmin", db: dbName },
      ],
    });
    print(`created user ${parsed.user} on ${dbName}`);
  } catch (error) {
    const message = String(error.message || error);
    if (error.codeName === "DuplicateKey" || /already exists/i.test(message)) {
      print(`user ${parsed.user} already present`);
    } else if (
      error.code === 13 ||
      /not authorized|unauthorized|requires authentication/i.test(message)
    ) {
      // Atlas manages database users in its own console; a normal project user
      // cannot create users. That is expected and not an error for this step.
      print(
        `cannot create user (${error.codeName || "unauthorized"}); ` +
          "Atlas-managed users are created in the Atlas UI — continuing",
      );
    } else {
      throw error;
    }
  }
}

try {
  appDb.getCollection("_meta").updateOne(
    { _id: "schema" },
    { $set: { version: 1, updatedAt: new Date() }, $setOnInsert: { createdAt: new Date() } },
    { upsert: true },
  );
} catch (error) {
  print(`warning: could not write the schema marker: ${error.message}`);
}

print(`lirify database ready: ${dbName}`);
