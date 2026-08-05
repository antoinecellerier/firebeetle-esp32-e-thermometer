#pragma once
// The sim compiles DisplayRenderer.cpp only, which reads no credentials.
// Shadowing the real header keeps host rendering independent of a gitignored
// file, so a fresh clone can run `make screenshots` without one.
