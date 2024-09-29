export const checkToken = (token) => {
  return fetch("/auth/token_check", {
    headers: {
      "Content-Type": "application/json",
      authorization: `Bearer ${token}`,
    },
  });
};
