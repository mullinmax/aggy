export const userLogin = (userData: any) => {
  // console.log(userData);
  const url = "/auth/login";
  return fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(userData),
  });
};
