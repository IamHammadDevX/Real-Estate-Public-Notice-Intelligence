-- Run once before starting FL/NY/NJ/MD/TX.
-- New state tables clone the already-tested GA schemas.

CREATE TABLE IF NOT EXISTS `FlPub` LIKE `GaPub`;
CREATE TABLE IF NOT EXISTS `NyPub` LIKE `GaPub`;
CREATE TABLE IF NOT EXISTS `NjPub` LIKE `GaPub`;
CREATE TABLE IF NOT EXISTS `MdPub` LIKE `GaPub`;
CREATE TABLE IF NOT EXISTS `TxPub` LIKE `GaPub`;

-- Some installations already contain older NY/NJ/etc. tables. Add every
-- scraper field separately so apply_migration.py can safely skip duplicates
-- while preserving those rows.
ALTER TABLE `FlPub` ADD COLUMN `owner_name` VARCHAR(500) NULL;
ALTER TABLE `FlPub` ADD COLUMN `parcel_number` VARCHAR(500) NULL;
ALTER TABLE `FlPub` ADD COLUMN `Date_Published` DATE NULL;
ALTER TABLE `FlPub` ADD COLUMN `county` VARCHAR(255) NULL;
ALTER TABLE `FlPub` ADD COLUMN `page_url` VARCHAR(1000) NULL;
ALTER TABLE `FlPub` ADD COLUMN `propstream_info` CHAR(1) NULL DEFAULT NULL;
ALTER TABLE `NyPub` ADD COLUMN `owner_name` VARCHAR(500) NULL;
ALTER TABLE `NyPub` ADD COLUMN `parcel_number` VARCHAR(500) NULL;
ALTER TABLE `NyPub` ADD COLUMN `Date_Published` DATE NULL;
ALTER TABLE `NyPub` ADD COLUMN `county` VARCHAR(255) NULL;
ALTER TABLE `NyPub` ADD COLUMN `page_url` VARCHAR(1000) NULL;
ALTER TABLE `NyPub` ADD COLUMN `propstream_info` CHAR(1) NULL DEFAULT NULL;
ALTER TABLE `NjPub` ADD COLUMN `owner_name` VARCHAR(500) NULL;
ALTER TABLE `NjPub` ADD COLUMN `parcel_number` VARCHAR(500) NULL;
ALTER TABLE `NjPub` ADD COLUMN `Date_Published` DATE NULL;
ALTER TABLE `NjPub` ADD COLUMN `county` VARCHAR(255) NULL;
ALTER TABLE `NjPub` ADD COLUMN `page_url` VARCHAR(1000) NULL;
ALTER TABLE `NjPub` ADD COLUMN `propstream_info` CHAR(1) NULL DEFAULT NULL;
ALTER TABLE `MdPub` ADD COLUMN `owner_name` VARCHAR(500) NULL;
ALTER TABLE `MdPub` ADD COLUMN `parcel_number` VARCHAR(500) NULL;
ALTER TABLE `MdPub` ADD COLUMN `Date_Published` DATE NULL;
ALTER TABLE `MdPub` ADD COLUMN `county` VARCHAR(255) NULL;
ALTER TABLE `MdPub` ADD COLUMN `page_url` VARCHAR(1000) NULL;
ALTER TABLE `MdPub` ADD COLUMN `propstream_info` CHAR(1) NULL DEFAULT NULL;
ALTER TABLE `TxPub` ADD COLUMN `owner_name` VARCHAR(500) NULL;
ALTER TABLE `TxPub` ADD COLUMN `parcel_number` VARCHAR(500) NULL;
ALTER TABLE `TxPub` ADD COLUMN `Date_Published` DATE NULL;
ALTER TABLE `TxPub` ADD COLUMN `county` VARCHAR(255) NULL;
ALTER TABLE `TxPub` ADD COLUMN `page_url` VARCHAR(1000) NULL;
ALTER TABLE `TxPub` ADD COLUMN `propstream_info` CHAR(1) NULL DEFAULT NULL;

ALTER TABLE `FlPub` MODIFY `Id` VARCHAR(191) NOT NULL, MODIFY `Notice` LONGTEXT, MODIFY `page_url` VARCHAR(1000);
ALTER TABLE `NyPub` MODIFY `Id` VARCHAR(191) NOT NULL, MODIFY `Notice` LONGTEXT, MODIFY `page_url` VARCHAR(1000);
ALTER TABLE `NjPub` MODIFY `Id` VARCHAR(191) NOT NULL, MODIFY `Notice` LONGTEXT, MODIFY `page_url` VARCHAR(1000);
ALTER TABLE `MdPub` MODIFY `Id` VARCHAR(191) NOT NULL, MODIFY `Notice` LONGTEXT, MODIFY `page_url` VARCHAR(1000);
ALTER TABLE `TxPub` MODIFY `Id` VARCHAR(191) NOT NULL, MODIFY `Notice` LONGTEXT, MODIFY `page_url` VARCHAR(1000);

CREATE TABLE IF NOT EXISTS `propstream_fl` LIKE `propstream_ga`;
CREATE TABLE IF NOT EXISTS `propstream_ny` LIKE `propstream_ga`;
CREATE TABLE IF NOT EXISTS `propstream_nj` LIKE `propstream_ga`;
CREATE TABLE IF NOT EXISTS `propstream_md` LIKE `propstream_ga`;
CREATE TABLE IF NOT EXISTS `propstream_tx` LIKE `propstream_ga`;

ALTER TABLE `propstream_fl` MODIFY `ga_id` VARCHAR(191);
ALTER TABLE `propstream_ny` MODIFY `ga_id` VARCHAR(191);
ALTER TABLE `propstream_nj` MODIFY `ga_id` VARCHAR(191);
ALTER TABLE `propstream_md` MODIFY `ga_id` VARCHAR(191);
ALTER TABLE `propstream_tx` MODIFY `ga_id` VARCHAR(191);

CREATE TABLE IF NOT EXISTS `ScrapeQueue` (
    `State` CHAR(2) NOT NULL,
    `Notice_Id` VARCHAR(191) NOT NULL,
    `Source_Url` VARCHAR(1000) NOT NULL,
    `Payload` LONGTEXT NULL,
    `Status` ENUM('pending','processing','complete','failed') NOT NULL DEFAULT 'pending',
    `Attempts` INT NOT NULL DEFAULT 0,
    `Last_Error` TEXT NULL,
    `Discovered_At` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `Updated_At` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    `Completed_At` TIMESTAMP NULL DEFAULT NULL,
    PRIMARY KEY (`State`, `Notice_Id`),
    KEY `idx_scrape_queue_state_status` (`State`, `Status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `ScrapeCheckpoints` (
    `State` CHAR(2) NOT NULL,
    `Adapter` VARCHAR(32) NOT NULL,
    `Cursor_Data` LONGTEXT NULL,
    `Discovery_Complete` TINYINT(1) NOT NULL DEFAULT 0,
    `Total_Discovered` INT NOT NULL DEFAULT 0,
    `Updated_At` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`State`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
