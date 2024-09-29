export const createUser = (userData: any) => {
  const url = "/auth/signup";
  return fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(userData),
  });
};
