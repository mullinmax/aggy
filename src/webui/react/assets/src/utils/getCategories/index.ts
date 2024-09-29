// export const getCategories = () => {
//   const response = fetch("/category/list", {
//     method: "GET",
//     // body: JSON.stringify(),
//     headers: {
//       "Content-Type": "application/json",
//     },
//   });

// };

export async function getCategories(token: string) {
  const response = await fetch("/category/list", {
    headers: {
      authorization: `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    throw new Error(`Error: ${response.statusText}`);
  }

  return response.json();
}
