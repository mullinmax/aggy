export const addCategory = async (userData: string, token: string) => {
  return fetch(`/category/create?category_name=${userData}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(userData),
  });
};
