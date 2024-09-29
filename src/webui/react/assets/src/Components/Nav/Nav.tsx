import React from "react";
// import Logo from ".";

interface NavProps {
  /** current page */
  currentPage: string;
  /** Sets current page state */
  setCurrentPage: Function;
}

export default function Nav({ currentPage, setCurrentPage }: NavProps) {
  const tabs = ["Home", "Login"];

  return (
    <div>
      <nav className="Nav-Container">
        {/* <div className="Mobile-Nav">
          <button className="Mobile-Nav-Btn" onClick={onClick}>
            <MenuIcon />
          </button>
        </div> */}
        <div className="Nav-Wrapper">
          <ul className="Nav-Inner-Wrapper">
            {tabs.map((tab) => (
              <li className="Nav-Item" key={tab}>
                <a
                  href={"#" + tab.toLowerCase()}
                  // Whenever a tab is clicked on,
                  // the current page is set through the handlePageChange props.
                  onClick={() => setCurrentPage(tab)}
                  className={
                    currentPage === tab ? "Nav-Link active" : "Nav-Link"
                  }
                >
                  {tab}
                </a>
              </li>
            ))}
          </ul>
        </div>
      </nav>
    </div>
  );
}
